# Standard library imports
import os
import re
import select
import struct
import threading
import time

# Third-party imports
import docker
from docker import DockerClient



def build_docker_images(
    dockerfile_dir=os.path.join(os.path.abspath(os.path.dirname(__file__)), "dockerfiles"),
    save_to_dir=os.path.join(os.path.abspath(os.path.dirname(__file__)), "container_images"),

):
    client = DockerClient.from_env()

    image_name = "openinterpreter-runtime-container"

    # Check if image already exists
    try:
        client.images.get(image_name)
        image_exists = True
    except:
        image_exists = False

    if not image_exists:
        print("[bold]No container images found. Building containers...[/bold]")

        # Verify that the specific Dockerfile exists
        dockerfile_name = "Dockerfile"
        dockerfile_path = os.path.join(dockerfile_dir, dockerfile_name)

        if not os.path.exists(dockerfile_path):
            print("[bold]ERROR: No Dockerfile found. Did you delete or rename them?[/bold]")
            raise RuntimeError(
                "No container Dockerfiles or images found. Use the correct naming schema 'Dockerfile.lang' and place Dockerfiles in the dockerfiles/ subdir of the module."
            )

        # Build the Docker image
        image, _ = client.images.build(
            path=dockerfile_dir, dockerfile=dockerfile_name, tag=image_name
        )

        # Save Docker image to a tar file
        tar_path = os.path.join(save_to_dir, f"{image_name}.tar")
        with open(tar_path, "wb") as f:
            for chunk in image.save():
                f.write(chunk)

class DockerStreamWrapper:
    def __init__(self, exec_id, sock):
        self.exec_id = exec_id
        self._sock = sock
        self._stdout_r, self._stdout_w = os.pipe()
        self._stderr_r, self._stderr_w = os.pipe()
        self.stdout = self.Stream(self, self._stdout_r)
        self.stderr = self.Stream(self, self._stderr_r)

        ## stdin pipe and fd. dosent need a pipe, but its easier and thread safe and less mem intensive than a queue.Queue()
        self._stdin_r, self._stdin_w = os.pipe()  # Pipe for stdin
        self.stdin = os.fdopen(self._stdin_w, 'w')
        self._stdin_buffer = b""  # Buffer for stdin data. more complex = better fr

        ## start recieving thread to watch socket, and send data from stdin pipe.
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()
    
    class Stream:
        def __init__(self, parent, read_fd):
            self.parent = parent
            self._read_fd = read_fd
            self._buffer = ""

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
                    data_to_write = os.read(self._stdin_r, 2048).decode('utf-8')
                    
                    # Remove escape characters for quotes but leave other backslashes untouched
                    data_to_write =  re.sub(r'\\([\'"])', r'\1', data_to_write)

                    data_to_write = data_to_write.replace('\\n', '\n')

                    self._stdin_buffer += data_to_write.encode()

                    # Check for newline and send line by line
                    while b'\n' in self._stdin_buffer:
                        newline_pos = self._stdin_buffer.find(b'\n')
                        line = self._stdin_buffer[:newline_pos + 1]  # Include the newline
                        self._stdin_buffer = self._stdin_buffer[newline_pos + 1:]


                        # Send the line to the Docker container
                        self._sock.sendall(line)

    def demux_docker_stream(self, data):
        stdout = ""
        stderr = ""
        offset = 0
        while offset + 8 <= len(data):
            header = data[offset:offset + 8]
            stream_type, length = struct.unpack('>BxxxL', header)
            offset += 8
            chunk = data[offset:offset + length].decode('utf-8')
            offset += length
            if stream_type == 1:
                stdout += chunk
            elif stream_type == 2:
                stderr += chunk

        return stdout, stderr

    def flush(self):
        pass

    def close(self):
        self._stop_event.set()
        self._thread.join()
        os.close(self._stdout_r)
        os.close(self._stdout_w)
        os.close(self._stderr_r)
        os.close(self._stderr_w)



class DockerProcWrapper:
    def __init__(self, command, session_path):
        self.client = docker.APIClient()
        self.image_name = "openinterpreter-runtime-container:latest"
        self.session_path = session_path
        self.id = os.path.basename(session_path)
        self.lang = self.extract_language_from_command(command)
        self.exec_id = None
        self.exec_socket = None

        # Initialize container
        self.init_container()

        self.init_exec_instance(command)
        

        self.wrapper = DockerStreamWrapper(self.exec_id, self.exec_socket)
        self.stdout = self.wrapper.stdout
        self.stderr = self.wrapper.stderr
        self.stdin = self.wrapper.stdin

        self.stdin.write(command + "\n")
    def init_container(self):
        self.container = None
        try:
            containers = self.client.containers(
                filters={"label": f"session_id={self.id}"}, all=True)
            if containers:
                self.container = containers[0]
                container_id = self.container.get('Id')
                container_info = self.client.inspect_container(container_id)
                if container_info.get('State', {}).get('Running') is False:
                    print(container_info.get('State', {}))
                    self.client.start(container=container_id)
                    self.wait_for_container_start(container_id)
            else:
                host_config = self.client.create_host_config(
                    binds={self.session_path: {'bind': '/mnt/data', 'mode': 'rw'}}
                )
                
                self.container = self.client.create_container(
                    image=self.image_name,
                    detach=True,
                    command="/bin/bash -i",
                    labels={'session_id': self.id},
                    host_config=host_config,
                    user="nobody",
                    stdin_open=True,
                    tty=False
                )

                self.client.start(container=self.container.get('Id'))
                self.wait_for_container_start(self.container.get('Id'))


        except Exception as e:
            print(f"An error occurred: {e}")

    def init_exec_instance(self, command):
        if self.container:
            self.exec_id = self.client.exec_create(
                self.container.get("Id"),
                cmd="/bin/bash",
                stdin=True,
                stdout=True,
                stderr=True,
                workdir="/mnt/data",
                user="nobody",
                tty=False

            )['Id']
            self.exec_socket = self.client.exec_start(
                self.exec_id, socket=True, tty=False, demux=False)._sock
            

    @staticmethod
    def extract_language_from_command(command):
        # Normalize the command to lower case for easier searching
        command_lower = command.lower()

        # Extract Python
        if "python" in command_lower or os.path.basename(command_lower).startswith("python"):
            return "python"

        # Extract R
        if re.search(r'\bR\b', command):
            return "r"

        # Extract Shell
        if any(shell in command_lower for shell in ["bash", "sh", "zsh", "fish"]):
            return "shell"

        # Extract Node.js
        if "node" in command_lower:
            return "javascript"

        # Return unknown if we can't determine the language
        return "unknown"

    def wait_for_container_start(self, container_id, timeout=30):
        start_time = time.time()
        while True:
            container_info = self.client.inspect_container(container_id)
            if container_info.get('State', {}).get('Running') is True:
                return True
            elif time.time() - start_time > timeout:
                raise TimeoutError(
                    "Container did not start within the specified timeout.")
            time.sleep(1)