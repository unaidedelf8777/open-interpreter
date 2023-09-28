import json
import os
import appdirs
from rich import print

from ..utils.display_markdown_message import display_markdown_message
from ..code_interpreters.container_utils.download_file import download_file_from_container
from ..code_interpreters.container_utils.upload_file import copy_file_to_container
from ..code_interpreters.create_code_interpreter import SESSION_IDS_BY_OBJECT


def handle_undo(self, arguments):
    # Removes all messages after the most recent user entry (and the entry itself).
    # Therefore user can jump back to the latest point of conversation.
    # Also gives a visual representation of the messages removed.

    if len(self.messages) == 0:
      return
    # Find the index of the last 'role': 'user' entry
    last_user_index = None
    for i, message in enumerate(self.messages):
        if message.get('role') == 'user':
            last_user_index = i

    removed_messages = []

    # Remove all messages after the last 'role': 'user'
    if last_user_index is not None:
        removed_messages = self.messages[last_user_index:]
        self.messages = self.messages[:last_user_index]

    print("") # Aesthetics.

    # Print out a preview of what messages were removed.
    for message in removed_messages:
      if 'content' in message and message['content'] != None:
        display_markdown_message(f"**Removed message:** `\"{message['content'][:30]}...\"`")
      elif 'function_call' in message:
        display_markdown_message(f"**Removed codeblock**") # TODO: Could add preview of code removed here.
    
    print("") # Aesthetics.

def handle_help(self, arguments):
    commands_description = {
      "%debug [true/false]": "Toggle debug mode. Without arguments or with 'true', it enters debug mode. With 'false', it exits debug mode.",
      "%reset": "Resets the current session.",
      "%undo": "Remove previous messages and its response from the message history.",
      "%save_message [path]": "Saves messages to a specified JSON path. If no path is provided, it defaults to 'messages.json'.",
      "%load_message [path]": "Loads messages from a specified JSON path. If no path is provided, it defaults to 'messages.json'.",
      "%help": "Show this help message.",
    }

    base_message = [
      "> **Available Commands:**\n\n"
    ]

    # Add each command and its description to the message
    for cmd, desc in commands_description.items():
      base_message.append(f"- `{cmd}`: {desc}\n")

    additional_info = [
      "\n\nFor further assistance, please join our community Discord or consider contributing to the project's development."
    ]

    # Combine the base message with the additional info
    full_message = base_message + additional_info

    display_markdown_message("".join(full_message))


def handle_debug(self, arguments=None):
    if arguments == "" or arguments == "true":
        display_markdown_message("> Entered debug mode")
        print(self.messages)
        self.debug_mode = True
    elif arguments == "false":
        display_markdown_message("> Exited debug mode")
        self.debug_mode = False
    else:
        display_markdown_message("> Unknown argument to debug command.")

def handle_reset(self, arguments):
    self.reset()
    display_markdown_message("> Reset Done")

def default_handle(self, arguments):
    display_markdown_message("> Unknown command")
    self.handle_help(arguments)

def handle_save_message(self, json_path):
    if json_path == "":
      json_path = "messages.json"
    if not json_path.endswith(".json"):
      json_path += ".json"
    with open(json_path, 'w') as f:
      json.dump(self.messages, f, indent=2)

    display_markdown_message(f"> messages json export to {os.path.abspath(json_path)}")

def handle_load_message(self, json_path):
    if json_path == "":
      json_path = "messages.json"
    if not json_path.endswith(".json"):
      json_path += ".json"
    with open(json_path, 'r') as f:
      self.load(json.load(f))

    display_markdown_message(f"> messages json loaded from {os.path.abspath(json_path)}")

def handle_container_upload(self, *args):
   
   if self.use_containers:
    for filepath in args:
        if os.path.exists(filepath):
          container_id = SESSION_IDS_BY_OBJECT.get(id(self))
          if container_id is not None:
            copy_file_to_container(container_id=container_id, local_file_path=filepath, file_path_in_container="/mnt/data") # /mnt/data is default workdir for container
          else:
             print("[BOLD]No container found to upload to. \n Please run any code to start one. this will be fixed in a later update[/BOLD]")
        else:
          continue
   else:
      print("[BOLD]File uploads are only used when using containerized code execution. ignoring command.[/BOLD]")
  


def handle_container_download(self, *args):
    if self.use_containers:
        # Check if any file paths are specified
        if not args:
            print("[BOLD]Please specify the file paths to download from the container.[/BOLD]")
            return

        container_id = SESSION_IDS_BY_OBJECT.get(id(self))
        if container_id is not None:
            for file_path_in_container in args:
                # Constructing the local file path
                local_dir = appdirs.user_data_dir(appname="Open Interpreter")
                local_file_path = os.path.join(local_dir, os.path.basename(file_path_in_container))
                
                # Checking if the file exists in the container, if not continue to the next file
                # You might need to implement a way to check if the file exists in the container
                if not self.file_exists_in_container(container_id, file_path_in_container):
                    print(f"[BOLD]File {file_path_in_container} does not exist in the container.[/BOLD]")
                    continue
                
                # Copying the file from the container to the local file path
                download_file_from_container(container_id=container_id, file_path_in_container=file_path_in_container, local_dir=local_file_path)
                print(f"[BOLD]File {file_path_in_container} downloaded to {local_file_path}.[/BOLD]")
        else:
            print("[BOLD]No container found to download from. \n Please run any code to start one. This will be fixed in a later update[/BOLD]")
    else:
        print("[BOLD]File downloads are only used when using containerized code execution. Ignoring command.[/BOLD]")



def handle_magic_command(self, user_input):
    # split the command into the command and the arguments, by the first whitespace
    switch = {
      "help": handle_help,
      "debug": handle_debug,
      "reset": handle_reset,
      "save_message": handle_save_message,
      "load_message": handle_load_message,
      "undo": handle_undo,
      "upload": handle_container_upload,
      "download": handle_container_download,
    }

    user_input = user_input[1:].strip()  # Capture the part after the `%`
    command = user_input.split(" ")[0]
    arguments = user_input[len(command):].strip()
    action = switch.get(command, default_handle)  # Get the function from the dictionary, or default_handle if not found
    action(self, arguments) # Execute the function