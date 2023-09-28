import tkinter as tk
import os
import time

class FileManager (tk.Tk):
    def __init__ (self, *args, **kwargs):
        tk.Tk.__init__ (self, *args, **kwargs)
        self.frame = tk.Frame (self)

        self.frame.rowconfigure (0, weight=1)
        self.frame.rowconfigure (1, weight=2)
        self.frame.rowconfigure (2, weight=10)
        self.frame.columnconfigure (0, weight=1)
        self.frame.columnconfigure (1, weight=1)
        self.frame.columnconfigure (2, weight=10)

        self.path_txt = tk.Entry (self.frame, fg='darkgreen', font='Arial20')
        self.path_txt.grid (row=0, column=0, columnspan=2, sticky="news", padx=1, pady=1)
        self.path_txt.bind ("<FocusIn>", lambda event: self.path_txt.delete (0, tk.END)
        if self.path_txt.get () == 'Enter a Path' else None)
        self.bind ("<Return>", self.open_dir)

        self.dir_listbox = tk.Listbox (self.frame)
        self.dir_listbox.grid (row=1, column=0, rowspan=2, columnspan=1, sticky="news", padx=1, pady=1)
        self.dir_listbox.bind ('<<ListboxSelect>>', self.dir_onselect)

        self.files_listbox = tk.Listbox (self.frame)
        self.files_listbox.grid (row=1, column=1, rowspan=2, columnspan=1, sticky="nesw", padx=1, pady=1)
        self.files_listbox.bind ('<<ListboxSelect>>', self.file_onselect)

        self.preview_label = tk.Label (self.frame)
        self.preview_label.grid (row=0, column=2, columnspan=1, rowspan=1, sticky="nesw", padx=1, pady=1)
        self.preview_label.config (bg="gray", fg="darkgreen", justify="center")

        self.files_attributes_listbox = tk.Listbox (self.frame)
        self.files_attributes_listbox.grid (row=1, column=2, columnspan=1, rowspan=1, sticky="nesw", padx=1, pady=1)
        #self.files_attributes_listbox.config (bg="lightgrey")

        self.text_preview_listbox = tk.Listbox (self.frame)
        self.text_preview_listbox.grid (row=2, column=2, columnspan=1, rowspan=1, sticky="nesw", padx=1, pady=1)
        self.text_preview_listbox.config(bg="lightgrey", selectmode="MULTIPLE")

        self.frame.grid (row=0, column=0, sticky="news", padx=1, pady=1)
        self.rowconfigure (0, weight=7)
        self.columnconfigure (0, weight=7)
        self.configure (background='gray')
        self.frame.configure (background='grey')

        self.title ('Text Preview File Explorer')
        self.minsize (800, 400)
        self.last_file = None
        cwd = os.getcwd()
        self.last_dir = cwd
        self.path_txt.insert (0, cwd)
        self.open_dir(None, cwd)


    def copy_selection(self):
        selected_text_list = [text_preview_listbox.get (i) for i in text_preview_listbox.curselection ()]
        print(selected_text_list)

    def open_dir (self, event=None, path=None):
        if not path:
            path = self.path_txt.get ()
        self.clear_all ()
        self.last_dir = "/".join (path.split ("/")[0:-1])  # save the last path
        # insert the back option ('..') in the directory listbox
        self.dir_listbox.insert (tk.END, '..')
        for root, dirs, files in os.walk (path):
            # update directories
            for dir in dirs:
                self.dir_listbox.insert (tk.END, dir)
            # update files
            for file in files:
                self.files_listbox.insert (tk.END, file)
            break

    def update_path (self, path):
        self.path_txt.delete (0, tk.END)
        self.path_txt.insert (0, path)

    def dir_onselect (self, event):
        if self.dir_listbox.curselection ():
            index = int (self.dir_listbox.curselection ()[0])
            dir = self.dir_listbox.get (index)
            if self.last_file:
                path = "/".join (self.path_txt.get ().split ("/")[0:-1])
                self.update_path (path)
                self.last_file = None
            if dir == '..' and self.last_dir:
                path = self.last_dir
            else:
                path = "/".join (self.path_txt.get ().split ("/") + [dir])
            self.update_path (path)
            self.open_dir (path=path)

    def file_onselect (self, event):
        if self.files_listbox.curselection ():
            index = int (self.files_listbox.curselection ()[0])
            file = self.files_listbox.get (index)
            if self.last_file:
                path = "/".join (self.path_txt.get ().split ("/")[0:-1] + [file])
            else:
                path = "/".join (self.path_txt.get ().split ("/") + [file])
            self.last_file = file
            self.update_path (path)
            self.show_file_attributes_listbox ()

    def show_file_attributes_listbox (self):
        path_to_file = self.path_txt.get ()
        file_obj = os.stat (path_to_file)
        file_size = file_obj.st_size
        file_size_kb = file_size / 1024
        self.files_attributes_listbox.delete (0, tk.END)  # make sure the listbox is cleared
        self.files_attributes_listbox.insert (tk.END, "File Size: " + str (file_size) + " bytes (" + str ("{0:.3f}".format(file_size_kb))+" Kbytes)")
        self.files_attributes_listbox.insert (tk.END, "Last Accessed: %s" % time.ctime (file_obj.st_atime))
        self.files_attributes_listbox.insert (tk.END, "Last Modified: %s" % time.ctime (file_obj.st_mtime))
        ext = os.path.splitext (path_to_file)[1]
        self.text_preview_listbox.delete (0, tk.END)

        with open (path_to_file) as f:
            try:
                content = f.readlines ()
            except Exception as e:
                print(e, " (not a ascii-encoded unicode string)")
                self.preview_label.config (text="other file type")
            else:
                print ("likely a ascii-encoded unicode string")
                self.show_text_preview (content)
        f.close ()

    def show_text_preview(self, lines):
        self.preview_label.config (text="text file")
        for line in lines:
            self.text_preview_listbox.insert(tk.END, line)
        self.files_attributes_listbox.insert (tk.END, "Lines: " + str(len(lines)))

    def clear_all (self):
        self.dir_listbox.delete (0, tk.END)
        self.files_listbox.delete (0, tk.END)
        self.files_attributes_listbox.delete (0, tk.END)


if __name__ == "__main__":
    myApp = FileManager ()
    myApp.mainloop ()