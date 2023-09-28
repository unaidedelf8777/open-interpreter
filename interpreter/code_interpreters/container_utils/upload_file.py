import docker
import tarfile
import os
import tempfile


def copy_file_to_container(container_id, local_file_path, file_path_in_container):
    # Validate input
    if not os.path.isfile(local_file_path):
        raise ValueError(f"The specified local file {local_file_path} does not exist.")
    
    # Create a Docker client
    client = docker.from_env()

    # Get the container
    container = client.containers.get(container_id)

    # Get the directory path and file name in the container
    dir_path_in_container = os.path.dirname(file_path_in_container)
    file_name = os.path.basename(file_path_in_container)

    # Create a temporary tar file
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        # Open the temporary tar file for writing
        with tarfile.open(temp_file.name, 'w') as tar:
            # Add the local file to the tar archive with the specified file name
            tar.add(local_file_path, arcname=file_name)
        
        # Read the temporary tar file into a binary stream
        with open(temp_file.name, 'rb') as f:
            file_data = f.read()

        # Use put_archive to copy the file into the container
        container.put_archive(dir_path_in_container, file_data)
    
    # Delete the temporary tar file
    os.remove(temp_file.name)