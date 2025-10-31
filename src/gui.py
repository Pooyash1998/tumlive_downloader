import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import tempfile
import threading
import queue
import os

from selenium import webdriver
from selenium.webdriver.firefox.webdriver import WebDriver
from selenium.webdriver.common.by import By
from time import sleep

import tum_live
import downloader

class TUMLiveDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TUM Live Downloader")
        self.root.geometry("800x600")
        
        # Variables
        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.keep_original_var = tk.BooleanVar(value=True)
        self.jump_cut_var = tk.BooleanVar(value=True)
        self.selected_courses = {}
        self.driver: webdriver.Firefox | None = None
        self.download_queue = queue.Queue()
        
        # Create the main frame
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=f"{tk.W}{tk.E}{tk.N}{tk.S}")
        
        # Create UI elements
        self.create_login_section()
        self.create_course_section()
        self.create_options_section()
        self.create_download_section()
        
    def create_login_section(self):
        login_frame = ttk.LabelFrame(self.main_frame, text="TUM Login", padding="5")
        login_frame.grid(row=0, column=0, columnspan=2, sticky=f"{tk.W}{tk.E}", pady=5)
        
        ttk.Label(login_frame, text="Username:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(login_frame, textvariable=self.username_var).grid(row=0, column=1, sticky=f"{tk.W}{tk.E}", padx=5)
        
        ttk.Label(login_frame, text="Password:").grid(row=1, column=0, sticky=tk.W)
        password_entry = ttk.Entry(login_frame, textvariable=self.password_var, show="*")
        password_entry.grid(row=1, column=1, sticky=f"{tk.W}{tk.E}", padx=5)
        
        ttk.Button(login_frame, text="Login", command=self.login).grid(row=2, column=0, columnspan=2, pady=5)
        
    def create_course_section(self):
        course_frame = ttk.LabelFrame(self.main_frame, text="Available Courses", padding="5")
        course_frame.grid(row=1, column=0, columnspan=2, sticky=f"{tk.W}{tk.E}{tk.N}{tk.S}", pady=5)
        
        self.course_tree = ttk.Treeview(course_frame, columns=("camera",), height=10)
        self.course_tree.heading("#0", text="Course")
        self.course_tree.heading("camera", text="Camera Type")
        self.course_tree.grid(row=0, column=0, sticky=f"{tk.W}{tk.E}{tk.N}{tk.S}")
        
        scrollbar = ttk.Scrollbar(course_frame, orient=tk.VERTICAL, command=self.course_tree.yview)
        scrollbar.grid(row=0, column=1, sticky=f"{tk.N}{tk.S}")
        self.course_tree.configure(yscrollcommand=scrollbar.set)
        
    def create_options_section(self):
        options_frame = ttk.LabelFrame(self.main_frame, text="Options", padding="5")
        options_frame.grid(row=2, column=0, columnspan=2, sticky=f"{tk.W}{tk.E}", pady=5)
        
        ttk.Label(options_frame, text="Output Directory:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(options_frame, textvariable=self.output_dir_var).grid(row=0, column=1, sticky=f"{tk.W}{tk.E}", padx=5)
        ttk.Button(options_frame, text="Browse", command=self.browse_output_dir).grid(row=0, column=2)
        
        ttk.Checkbutton(options_frame, text="Keep Original Files", variable=self.keep_original_var).grid(row=1, column=0, columnspan=2, sticky=tk.W)
        ttk.Checkbutton(options_frame, text="Jump Cut Videos", variable=self.jump_cut_var).grid(row=2, column=0, columnspan=2, sticky=tk.W)
        
    def create_download_section(self):
        download_frame = ttk.LabelFrame(self.main_frame, text="Download Progress", padding="5")
        download_frame.grid(row=3, column=0, columnspan=2, sticky=f"{tk.W}{tk.E}", pady=5)
        
        self.progress = ttk.Progressbar(download_frame, mode='indeterminate')
        self.progress.grid(row=0, column=0, sticky=f"{tk.W}{tk.E}")
        
        ttk.Button(download_frame, text="Download Selected", command=self.start_download).grid(row=1, column=0, pady=5)
        
    def browse_output_dir(self):
        directory = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if directory:
            self.output_dir_var.set(directory)
            
    def login(self):
        username = self.username_var.get()
        password = self.password_var.get()
        
        if not username or not password:
            messagebox.showerror("Error", "Please enter both username and password")
            return
            
        def login_thread():
            try:
                self.driver = tum_live.login(username, password)
                self.root.after(0, self.load_courses)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Login Error", str(e)))
        
        threading.Thread(target=login_thread).start()
        
    def load_courses(self):
        if not self.driver:
            messagebox.showerror("Error", "Not logged in")
            return
            
        self.course_tree.delete(*self.course_tree.get_children())
        self.driver.get("https://live.rbg.tum.de/old/")
        
        # Find all course links
        links = self.driver.find_elements(By.XPATH, ".//a")
        for link in links:
            href = link.get_attribute("href")
            if href and "course/" in href:
                course_id = href.split("/")[-1]
                course_name = link.text.strip()
                if course_name:
                    for camera_type in ["COMB", "PRES", "CAM"]:
                        item_id = f"{course_name}:{camera_type}"
                        self.course_tree.insert("", "end", item_id, text=course_name, values=(camera_type,))
                        self.selected_courses[item_id] = {"id": course_id, "camera": camera_type}
                        
    def start_download(self):
        selected_items = self.course_tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "Please select at least one course to download")
            return
            
        output_dir = Path(self.output_dir_var.get())
        if not output_dir.exists():
            messagebox.showerror("Error", "Output directory does not exist")
            return
            
        # Prepare download parameters
        tmp_dir = Path(tempfile.gettempdir(), "tum_video_scraper")
        if not tmp_dir.exists():
            tmp_dir.mkdir(parents=True)
            
        # Start download process in a separate thread
        threading.Thread(target=self.download_process, args=(selected_items, output_dir, tmp_dir)).start()
        
    def download_process(self, selected_items, output_dir, tmp_dir):
        if not self.driver:
            messagebox.showerror("Error", "Not logged in")
            return
            
        try:
            videos_for_subject = {}
            
            # Get videos for each selected course
            for item_id in selected_items:
                course_info = self.selected_courses[item_id]
                course_name = item_id.split(":")[0]
                
                self.root.after(0, lambda: self.progress.start())
                playlists = tum_live.get_video_links_of_subject(
                    self.driver,
                    course_info["id"],
                    course_info["camera"]
                )
                videos_for_subject[course_name] = playlists
                
            # Download videos
            spawned_processes = []
            for subject, playlists in videos_for_subject.items():
                subject_folder = Path(output_dir, subject)
                subject_folder.mkdir(exist_ok=True)
                
                spawned_processes += downloader.download_list_of_videos(
                    playlists,
                    subject_folder,
                    tmp_dir,
                    self.keep_original_var.get(),
                    self.jump_cut_var.get(),
                    threading.Semaphore(3)  # Maximum 3 parallel downloads
                )
                
            # Wait for all downloads to complete
            for process in spawned_processes:
                process.join()
                
            self.root.after(0, lambda: self.progress.stop())
            self.root.after(0, lambda: messagebox.showinfo("Success", "Downloads completed successfully!"))
            
        except Exception as e:
            self.root.after(0, lambda: self.progress.stop())
            self.root.after(0, lambda: messagebox.showerror("Error", f"Download failed: {str(e)}"))

def main():
    root = tk.Tk()
    app = TUMLiveDownloaderGUI(root)
    root.mainloop()
    
if __name__ == "__main__":
    main()