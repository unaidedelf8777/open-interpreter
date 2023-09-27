# Standard library imports
import atexit
import hashlib
import json
import os
import re
import select
import shutil
import struct
import subprocess
import threading
import time


# Third-party imports
import docker
from docker import DockerClient
from docker.errors import DockerException
from rich import print as Print


def get_files_hash(*file_paths):
    """Return the SHA256 hash of multiple files."""
    hasher = hashlib.sha256()
    for file_path in file_paths:
        with open(file_path, "rb") as f:
            while chunk := f.read(4096):
                hasher.update(chunk)
    return hasher.hexdigest()


def build_docker_images(
    dockerfile_dir=os.path.join(os.path.abspath(os.path.dirname(__file__)), "dockerfiles"),
):
    """
    Builds a Docker image for the Open Interpreter runtime container if needed.

    Args:
        dockerfile_dir (str): The directory containing the Dockerfile and requirements.txt files.

    Returns:
        None
    """
    try:
        client = DockerClient.from_env()
    except DockerException:
        Print("ERROR: Could not connect to Docker daemon. Is Docker Engine installed and running?")
        Print(
            "\nFor information on Docker installation, visit: https://docs.docker.com/engine/install/"
        )
        return

    image_name = "openinterpreter-runtime-container"
    hash_file_path = os.path.join(dockerfile_dir, "hash.json")

    dockerfile_name = "Dockerfile"
    requirements_name = "requirements.txt"
    dockerfile_path = os.path.join(dockerfile_dir, dockerfile_name)
    requirements_path = os.path.join(dockerfile_dir, requirements_name)

    if not os.path.exists(dockerfile_path) or not os.path.exists(requirements_path):
        Print("ERROR: Dockerfile or requirements.txt not found. Did you delete or rename them?")
        raise RuntimeError(
            "No container Dockerfiles or requirements.txt found. Make sure they are in the dockerfiles/ subdir of the module."
        )

    current_hash = get_files_hash(dockerfile_path, requirements_path)

    stored_hashes = {}
    if os.path.exists(hash_file_path):
        with open(hash_file_path, "rb") as f:
            stored_hashes = json.load(f)

    original_hash = stored_hashes.get("original_hash")
    previous_hash = stored_hashes.get("last_hash")

    if current_hash == original_hash:
        images = client.images.list(name=image_name, all=True)
        if not images:
            Print("Downloading default image from Docker Hub, please wait...")
            client.images.pull("unaidedelf/openinterpreter-runtime-container", tag="latest")
    elif current_hash != previous_hash:
        Print("Dockerfile or requirements.txt has changed. Building container...")

        try:
            # Run the subprocess without capturing stdout and stderr
            # This will allow Docker's output to be printed to the console in real-time
            subprocess.run(
                [
                    "docker",
                    "build",
                    "-t",
                    f"{image_name}:latest",
                    dockerfile_dir,
                ],
                check=True,  # This will raise a CalledProcessError if the command returns a non-zero exit code
                text=True,
            )

            # Update the stored current hash
            stored_hashes["current_hash"] = current_hash
            with open(hash_file_path, "w", encoding="utf-8") as f:
                json.dump(stored_hashes, f)

        except subprocess.CalledProcessError:
            # Suppress Docker's error messages and display your own error message
            Print("Docker Build Error: Building Docker image failed. Please review the error message above and resolve the issue.")

        except FileNotFoundError:
            Print("ERROR: The 'docker' command was not found on your system.")
            Print(
                "Please ensure Docker Engine is installed and the 'docker' command is available in your PATH."
            )
            Print(
                "For information on Docker installation, visit: https://docs.docker.com/engine/install/"
            )
            Print("If Docker is installed, try starting a new terminal session.")


class DockerStreamWrapper:
    """
    A wrapper class for Docker container streams.

    This class provides a way to interact with the input/output streams of a Docker container.
    It creates pipes for stdin, stdout, and stderr, and starts a thread to listen for data on the socket.
    """

    def __init__(self, exec_id, sock):
        self.exec_id = exec_id
        self._sock = sock
        self._stdout_r, self._stdout_w = os.pipe()
        self._stderr_r, self._stderr_w = os.pipe()
        self.stdout = self.Stream(self, self._stdout_r)
        self.stderr = self.Stream(self, self._stderr_r)

        self._stdin_r, self._stdin_w = os.pipe()  # Pipe for stdin
        self.stdin = os.fdopen(self._stdin_w, "w")
        self._stdin_buffer = b""  # Buffer for stdin data. more complex = better fr

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    class Stream:
        """
        A class representing a stream of data.

        Attributes:
            parent (object): The parent object that created the stream.
            _read_fd (int): The file descriptor for the read end of the stream.
            _buffer (str): The buffer for the stream data.
        """
        def __init__(self, parent, read_fd):
            self.parent = parent
            self._read_fd = read_fd
            self._buffer = ""
        
        ### CAUTION: For some reason when formatting the document, it deletes the readline method. i dont understand why, but it does so dont format this doc.
        def readline(self, timeout=3):
            while '\n' not in self._buffer:
                ready_to_read, _, _ = select.select([self._read_fd], [], [], timeout)
                if not ready_to_read:
                    return ''
                chunk = os.read(self._read_fd, 1024).decode('utf-8')
                self._buffer += chunk

            newline_pos = self._buffer.find('\n')
            line = self._buffer[:newline_pos]
            self._buffer = self._buffer[newline_pos + 1:]
            return line

    def _listen(self):
        while not self._stop_event.is_set():
            ready_to_read, _, _ = select.select([self._sock, self._stdin_r], [], [], 1)

            for s in ready_to_read:
                if s == self._sock:
                    raw_data = self._sock.recv(2048)
                    stdout, stderr = self.demux_docker_stream(raw_data)
                    os.write(self._stdout_w, stdout.encode())
                    os.write(self._stderr_w, stderr.encode())
                elif s == self._stdin_r:
                    # Read from the read end of the stdin pipe and add to the buffer
                    data_to_write = os.read(self._stdin_r, 2048).decode("utf-8")

                    # Remove escape characters for quotes but leave other backslashes untouched
                    data_to_write = re.sub(r'\\([\'"])', r"\1", data_to_write)

                    data_to_write = data_to_write.replace("\\n", "\n")

                    self._stdin_buffer += data_to_write.encode()

                    # Check for newline and send line by line
                    while b"\n" in self._stdin_buffer:
                        newline_pos = self._stdin_buffer.find(b"\n")
                        line = self._stdin_buffer[: newline_pos + 1]  # Include the newline
                        self._stdin_buffer = self._stdin_buffer[newline_pos + 1 :]

                        # Send the line to the Docker container
                        self._sock.sendall(line)

    @staticmethod
    def demux_docker_stream(data):
        """
        Demultiplexes a Docker stream into stdout and stderr.

        Args:
            data (bytes): The Docker stream to demultiplex.

        Returns:
            Tuple[str, str]: A tuple containing the stdout and stderr streams.
        """
        stdout = ""
        stderr = ""
        offset = 0
        while offset + 8 <= len(data):
            header = data[offset : offset + 8]
            (stream_type, length) = struct.unpack(">BxxxL", header)
            offset += 8
            chunk = data[offset : offset + length].decode("utf-8")
            offset += length
            if stream_type == 1:
                stdout += chunk
            elif stream_type == 2:
                stderr += chunk
        return (stdout, stderr)

    @staticmethod
    def flush():
        """
        This method is not implemented as we use .sendall when sending data to the socket.
        It is only here for the sake of being identical to the Subprocess.POPEN interface.
        """

    def close(self):
        self._stop_event.set()
        self._thread.join()
        os.close(self._stdout_r)
        os.close(self._stdout_w)
        os.close(self._stderr_r)
        os.close(self._stderr_w)


class DockerProcWrapper:
    """
    Initializes a DockerProcWrapper instance.

    Args:
        command (str): The command to be executed in the Docker container.
        session_path (str): The path to the session directory.

    Returns:
        None

    Raises:
        TimeoutError: Raised when the container fails to start within the specified timeout.

    """
    def __init__(self, command, session_path):
        self.client = docker.APIClient()
        self.image_name = "openinterpreter-runtime-container:latest"
        self.session_path = session_path
        self.id = os.path.basename(session_path)
        self.exec_id = None
        self.exec_socket = None
        atexit.register(atexit_destroy, self)

        if not os.path.exists(session_path):
            os.makedirs(session_path)

        # Initialize container
        self.init_container()

        self.init_exec_instance()

        self.wrapper = DockerStreamWrapper(self.exec_id, self.exec_socket)
        self.stdout = self.wrapper.stdout
        self.stderr = self.wrapper.stderr
        self.stdin = self.wrapper.stdin
        self.stdin.write(command + "\n")

    def init_container(self):
        """
        Initializes a Docker container for the interpreter session.

        If a container with the session ID label already exists, it will be used.
        Otherwise, a new container will be created with the specified image and host configuration.

        Raises:
            docker.errors.APIError: If an error occurs while interacting with the Docker API.
        """
        self.container = None
        try:
            if containers := self.client.containers(
                filters={"label": f"session_id={self.id}"}, all=True
            ):
                self.container = containers[0]
                container_id = self.container.get("Id")
                container_info = self.client.inspect_container(container_id)
                if container_info.get("State", {}).get("Running") is False:
                    Print(container_info.get("State", {}))
                    self.client.start(container=container_id)
                    self.wait_for_container_start(container_id)
            else:
                host_config = self.client.create_host_config(
                    binds={self.session_path: {"bind": "/mnt/data", "mode": "rw"}}
                )

                self.container = self.client.create_container(
                    image=self.image_name,
                    detach=True,
                    command="/bin/bash -i",
                    labels={"session_id": self.id},
                    host_config=host_config,
                    user="nobody",
                    stdin_open=True,
                    tty=False,
                )

                self.client.start(container=self.container.get("Id"))
                self.wait_for_container_start(self.container.get("Id"))

        except docker.errors.APIError as api_error:
            Print(f"An error occurred: {api_error}")

    def init_exec_instance(self):
        """
        Initializes the execution instance for the container.

        If a container exists, this method creates an execution instance for the container using the Docker API.
        The execution instance is created with the following parameters:
        - cmd: "/bin/bash"
        - stdin: True
        - stdout: True
        - stderr: True
        - workdir: "/mnt/data"
        - user: "nobody"
        - tty: False

        Returns:
        None
        """
        if self.container:
            self.exec_id = self.client.exec_create(
                self.container.get("Id"),
                cmd="/bin/bash",
                stdin=True,
                stdout=True,
                stderr=True,
                workdir="/mnt/data",
                user="docker",
                tty=False,
            )["Id"]
            self.exec_socket = self.client.exec_start(
                self.exec_id, socket=True, tty=False, demux=False
            )._sock

    def wait_for_container_start(self, container_id, timeout=30):
        """
        Waits for a container to start running.

        Args:
            container_id (str): The ID of the container to wait for.
            timeout (int, optional): The maximum amount of time to wait for the container to start, in seconds. Defaults to 30.

        Raises:
            TimeoutError: If the container does not start running within the specified timeout.

        Returns:
            bool: True if the container starts running within the specified timeout, False otherwise.
        """
        start_time = time.time()
        while True:
            container_info = self.client.inspect_container(container_id)
            if container_info.get("State", {}).get("Running") is True:
                return True
            if time.time() - start_time > timeout:
                raise TimeoutError("Container did not start within the specified timeout.")
            time.sleep(1)


def atexit_destroy(self):
    """
    Deletes the session directory and stops/removes the container associated with the current session.

    Args:
        self: The current instance of the ContainerUtils class.
    """

    shutil.rmtree(self.session_path)
    self.client.stop(self.container.get("Id"))
    self.client.remove_container(self.container.get("Id"))
