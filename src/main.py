import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import threading
import queue
import tempfile
import os
import yaml
from multiprocessing import Semaphore
from selenium import webdriver
from selenium.webdriver.common.by import By
import tum_live
import downloader

# Configuration functions
def load_config_file():
    """Load configuration from config file"""
    config_file_paths = [
        Path("config.yml"),
        Path("../config.yml"), 
        Path("config.yaml"),
        Path("../config.yaml")
    ]
    
    for path in config_file_paths:
        if path.exists():
            try:
                with open(path, "r") as config_file:
                    cfg = yaml.load(config_file, Loader=yaml.SafeLoader)
                    return cfg if cfg else {}
            except Exception:
                continue
    return {}

def parse_destination_folder(cfg) -> Path:
    """Parse and create destination folder from config"""
    destination_folder_path = None
    if 'Output-Folder' in cfg: 
        destination_folder_path = Path(cfg['Output-Folder'])
    if not destination_folder_path:
        destination_folder_path = Path.home() / "Downloads"
    destination_folder_path = Path(destination_folder_path)
    if not destination_folder_path.is_dir():
        destination_folder_path.mkdir(exist_ok=True)
    return destination_folder_path

def parse_tmp_folder(cfg) -> Path:
    """Parse and create temporary folder from config"""
    tmp_directory = None
    if 'Temp-Dir' in cfg:
        tmp_directory = Path(cfg['Temp-Dir'])
    if not tmp_directory:
        tmp_directory = Path(tempfile.gettempdir(), "tum_video_scraper")
    if not os.path.isdir(tmp_directory):
        tmp_directory.mkdir(exist_ok=True)
    return tmp_directory

def parse_maximum_parallel_downloads(cfg) -> int:
    """Parse maximum parallel downloads from config"""
    return cfg.get('Maximum-Parallel-Downloads', 3)

def parse_username_password(cfg) -> tuple[str | None, str | None]:
    """Parse username and password from config"""
    username = cfg.get('Username', None)
    password = cfg.get('Password', None)
    return username, password

class TUMLiveDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TUM Live Downloader")
        self.root.geometry("400x500")
        self.root.configure(bg='#f0f0f0')
        
        # Center the window
        self.center_window()
        
        # Load configuration
        self.config = load_config_file()
        self.username, self.password = parse_username_password(self.config)
        
        # Initialize variables
        self.driver: webdriver.Firefox | None = None
        self.selected_courses = {}
        self.download_queue = queue.Queue()
        
        # Start with login page
        self.show_login_page()
    
    def center_window(self):
        """Center the window on screen"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
    
    def show_login_page(self):
        """Create modern login page"""
        # Clear any existing widgets
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # Main container
        main_frame = tk.Frame(self.root, bg='#f0f0f0')
        main_frame.pack(fill='both', expand=True, padx=40, pady=60)
        
        # Title
        title_label = tk.Label(main_frame, text="TUM Live Downloader", 
                              font=('Helvetica', 24, 'bold'), 
                              bg='#f0f0f0', fg='#333333')
        title_label.pack(pady=(0, 40))
        
        # Login card
        login_frame = tk.Frame(main_frame, bg='white', relief='flat', bd=0)
        login_frame.pack(fill='x', pady=20)
        
        # Add shadow effect
        shadow_frame = tk.Frame(main_frame, bg='#e0e0e0', height=2)
        shadow_frame.pack(fill='x', pady=(0, 20))
        
        # Login form
        form_frame = tk.Frame(login_frame, bg='white')
        form_frame.pack(padx=30, pady=30, fill='x')
        
        # Username section
        if self.username:
            # Existing user card
            user_card = tk.Frame(form_frame, bg='#f8f9fa', relief='solid', bd=1)
            user_card.pack(fill='x', pady=(0, 20))
            
            user_info_frame = tk.Frame(user_card, bg='#f8f9fa')
            user_info_frame.pack(padx=15, pady=15, fill='x')
            
            # User avatar (placeholder)
            avatar_frame = tk.Frame(user_info_frame, bg='#007acc', width=40, height=40)
            avatar_frame.pack(side='left', padx=(0, 15))
            avatar_frame.pack_propagate(False)
            
            avatar_label = tk.Label(avatar_frame, text=self.username[0].upper(), 
                                  bg='#007acc', fg='white', font=('Helvetica', 16, 'bold'))
            avatar_label.pack(expand=True)
            
            # User info
            user_text_frame = tk.Frame(user_info_frame, bg='#f8f9fa')
            user_text_frame.pack(side='left', fill='x', expand=True)
            
            tk.Label(user_text_frame, text=self.username, 
                    font=('Helvetica', 12, 'bold'), bg='#f8f9fa', fg='#333').pack(anchor='w')
            tk.Label(user_text_frame, text="Saved account", 
                    font=('Helvetica', 9), bg='#f8f9fa', fg='#666').pack(anchor='w')
            
            # Login button for saved user
            login_btn = tk.Button(form_frame, text="Continue", 
                                command=self.login_with_saved_credentials,
                                bg='#007acc', fg='white', font=('Helvetica', 11, 'bold'),
                                relief='flat', padx=20, pady=10, cursor='hand2')
            login_btn.pack(fill='x', pady=(0, 15))
            
            # Separator
            separator_frame = tk.Frame(form_frame, bg='white')
            separator_frame.pack(fill='x', pady=15)
            
            tk.Frame(separator_frame, bg='#e0e0e0', height=1).pack(fill='x', side='left', expand=True)
            tk.Label(separator_frame, text=" or ", bg='white', fg='#666', 
                    font=('Helvetica', 9)).pack(side='left', padx=10)
            tk.Frame(separator_frame, bg='#e0e0e0', height=1).pack(fill='x', side='left', expand=True)
        
        # Manual login form
        tk.Label(form_frame, text="Username", font=('Helvetica', 10), 
                bg='white', fg='#333').pack(anchor='w', pady=(0, 5))
        
        self.username_entry = tk.Entry(form_frame, font=('Helvetica', 11), 
                                      relief='solid', bd=1, padx=10, pady=8)
        self.username_entry.pack(fill='x', pady=(0, 15))
        
        tk.Label(form_frame, text="Password", font=('Helvetica', 10), 
                bg='white', fg='#333').pack(anchor='w', pady=(0, 5))
        
        self.password_entry = tk.Entry(form_frame, font=('Helvetica', 11), 
                                      show='*', relief='solid', bd=1, padx=10, pady=8)
        self.password_entry.pack(fill='x', pady=(0, 20))
        
        # Login button
        login_btn = tk.Button(form_frame, text="Login", 
                            command=self.login_with_manual_credentials,
                            bg='#28a745', fg='white', font=('Helvetica', 11, 'bold'),
                            relief='flat', padx=20, pady=10, cursor='hand2')
        login_btn.pack(fill='x')
        
        # Status label
        self.status_label = tk.Label(form_frame, text="", bg='white', fg='#dc3545', 
                                    font=('Helvetica', 9))
        self.status_label.pack(pady=(10, 0))
    
    def login_with_saved_credentials(self):
        """Login using saved credentials"""
        self.perform_login(self.username, self.password)
    
    def login_with_manual_credentials(self):
        """Login using manually entered credentials"""
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        
        if not username or not password:
            self.status_label.config(text="Please enter both username and password")
            return
        
        self.perform_login(username, password)
    
    def perform_login(self, username, password):
        """Perform the actual login process"""
        self.status_label.config(text="Logging in...", fg='#007acc')
        
        def login_thread():
            try:
                self.driver = tum_live.login(username, password)
                self.root.after(0, self.show_main_page)
            except Exception as e:
                self.root.after(0, lambda: self.status_label.config(
                    text=f"Login failed: {str(e)}", fg='#dc3545'))
        
        threading.Thread(target=login_thread, daemon=True).start()
    
    def show_main_page(self):
        """Show the main application page"""
        # Clear login page
        for widget in self.root.winfo_children():
            widget.destroy()
        
        # Resize window for main page
        self.root.geometry("900x700")
        self.center_window()
        
        # Get config values
        output_dir = parse_destination_folder(self.config)
        self.tmp_dir = parse_tmp_folder(self.config)
        self.max_parallel_downloads = parse_maximum_parallel_downloads(self.config)
        
        # Initialize variables
        self.output_dir_var = tk.StringVar(value=str(output_dir))
        self.keep_original_var = tk.BooleanVar(value=self.config.get('Keep-Original-File', True))
        self.jump_cut_var = tk.BooleanVar(value=self.config.get('Jumpcut', True))
        
        # Create main interface
        self.create_main_interface()
        
        # Load courses automatically
        self.load_courses()
    
    def create_main_interface(self):
        """Create the main application interface"""
        # Main container
        main_container = tk.Frame(self.root, bg='#f0f0f0')
        main_container.pack(fill='both', expand=True, padx=20, pady=20)
        
        # Header
        header_frame = tk.Frame(main_container, bg='#f0f0f0')
        header_frame.pack(fill='x', pady=(0, 20))
        
        tk.Label(header_frame, text="TUM Live Downloader", 
                font=('Helvetica', 20, 'bold'), bg='#f0f0f0', fg='#333').pack(side='left')
        
        logout_btn = tk.Button(header_frame, text="Logout", command=self.logout,
                              bg='#dc3545', fg='white', font=('Helvetica', 9),
                              relief='flat', padx=15, pady=5, cursor='hand2')
        logout_btn.pack(side='right')
        
        # Course section
        self.create_course_section(main_container)
        
        # Options section
        self.create_options_section(main_container)
        
        # Download section
        self.create_download_section(main_container)
    
    def logout(self):
        """Logout and return to login page"""
        if self.driver:
            self.driver.quit()
            self.driver = None
        self.show_login_page()
    
    def create_course_section(self, parent):
        """Create course selection section"""
        course_frame = tk.LabelFrame(parent, text="Available Lectures", 
                                    bg='white', font=('Helvetica', 11, 'bold'),
                                    relief='solid', bd=1, padx=10, pady=10)
        course_frame.pack(fill='both', expand=True, pady=(0, 15))
        
        # Loading label
        self.loading_label = tk.Label(course_frame, text="Loading lectures...", 
                                     bg='white', fg='#666', font=('Helvetica', 10))
        self.loading_label.pack(pady=20)
        
        # Treeview for courses
        tree_frame = tk.Frame(course_frame, bg='white')
        tree_frame.pack(fill='both', expand=True)
        
        self.course_tree = ttk.Treeview(tree_frame, columns=("camera",), height=12, 
                                       selectmode='extended')
        self.course_tree.heading("#0", text="Lecture")
        self.course_tree.heading("camera", text="Camera Type")
        self.course_tree.column("camera", width=120)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.course_tree.yview)
        scrollbar.pack(side='right', fill='y')
        self.course_tree.configure(yscrollcommand=scrollbar.set)
        self.course_tree.pack(side='left', fill='both', expand=True)
    
    def create_options_section(self, parent):
        """Create options section"""
        options_frame = tk.LabelFrame(parent, text="Download Options", 
                                     bg='white', font=('Helvetica', 11, 'bold'),
                                     relief='solid', bd=1, padx=10, pady=10)
        options_frame.pack(fill='x', pady=(0, 15))
        
        # Output directory
        dir_frame = tk.Frame(options_frame, bg='white')
        dir_frame.pack(fill='x', pady=(0, 10))
        
        tk.Label(dir_frame, text="Output Directory:", bg='white', 
                font=('Helvetica', 10)).pack(anchor='w')
        
        dir_input_frame = tk.Frame(dir_frame, bg='white')
        dir_input_frame.pack(fill='x', pady=(5, 0))
        
        self.output_entry = tk.Entry(dir_input_frame, textvariable=self.output_dir_var,
                                    font=('Helvetica', 10), relief='solid', bd=1, padx=8, pady=6)
        self.output_entry.pack(side='left', fill='x', expand=True, padx=(0, 10))
        
        browse_btn = tk.Button(dir_input_frame, text="Browse", command=self.browse_output_dir,
                              bg='#6c757d', fg='white', font=('Helvetica', 9),
                              relief='flat', padx=15, pady=6, cursor='hand2')
        browse_btn.pack(side='right')
        
        # Checkboxes
        checkbox_frame = tk.Frame(options_frame, bg='white')
        checkbox_frame.pack(fill='x')
        
        keep_check = tk.Checkbutton(checkbox_frame, text="Keep Original Files", 
                                   variable=self.keep_original_var, bg='white',
                                   font=('Helvetica', 10), anchor='w')
        keep_check.pack(anchor='w', pady=2)
        
        jump_check = tk.Checkbutton(checkbox_frame, text="Jump Cut Videos", 
                                   variable=self.jump_cut_var, bg='white',
                                   font=('Helvetica', 10), anchor='w')
        jump_check.pack(anchor='w', pady=2)
        
        # Max downloads info
        tk.Label(checkbox_frame, text=f"Max Parallel Downloads: {self.max_parallel_downloads}", 
                bg='white', fg='#666', font=('Helvetica', 9)).pack(anchor='w', pady=(5, 0))
    
    def create_download_section(self, parent):
        """Create download section"""
        download_frame = tk.LabelFrame(parent, text="Download", 
                                      bg='white', font=('Helvetica', 11, 'bold'),
                                      relief='solid', bd=1, padx=10, pady=10)
        download_frame.pack(fill='x')
        
        # Progress bar
        self.progress = ttk.Progressbar(download_frame, mode='indeterminate')
        self.progress.pack(fill='x', pady=(0, 10))
        
        # Download button
        self.download_btn = tk.Button(download_frame, text="Download Selected Lectures", 
                                     command=self.start_download,
                                     bg='#007acc', fg='white', font=('Helvetica', 11, 'bold'),
                                     relief='flat', padx=20, pady=10, cursor='hand2')
        self.download_btn.pack(fill='x')
        
        # Status label
        self.download_status = tk.Label(download_frame, text="", bg='white', 
                                       font=('Helvetica', 9), fg='#666')
        self.download_status.pack(pady=(10, 0))
    
    def browse_output_dir(self):
        """Browse for output directory"""
        directory = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if directory:
            self.output_dir_var.set(directory)
    
    def load_courses(self):
        """Load available courses"""
        if not self.driver:
            return
        
        def load_thread():
            try:
                self.root.after(0, lambda: self.loading_label.config(text="Loading lectures..."))
                
                self.driver.get("https://live.rbg.tum.de/")
                
                # Clear existing courses
                self.root.after(0, lambda: self.course_tree.delete(*self.course_tree.get_children()))
                
                # Find all course links
                links = self.driver.find_elements(By.XPATH, ".//a")
                courses_found = 0
                
                for link in links:
                    href = link.get_attribute("href")
                    if href and "course/" in href:
                        course_id = href.split("/")[-1]
                        course_name = link.text.strip()
                        if course_name:
                            for camera_type in ["COMB", "PRES", "CAM"]:
                                item_id = f"{course_name}:{camera_type}"
                                self.root.after(0, lambda cn=course_name, ct=camera_type, iid=item_id, cid=course_id: 
                                               self.add_course_item(cn, ct, iid, cid))
                                courses_found += 1
                
                self.root.after(0, lambda: self.loading_label.config(
                    text=f"Found {courses_found} lectures" if courses_found > 0 else "No lectures found"))
                
            except Exception as e:
                self.root.after(0, lambda: self.loading_label.config(
                    text=f"Error loading lectures: {str(e)}"))
        
        threading.Thread(target=load_thread, daemon=True).start()
    
    def add_course_item(self, course_name, camera_type, item_id, course_id):
        """Add course item to tree"""
        self.course_tree.insert("", "end", item_id, text=course_name, values=(camera_type,))
        self.selected_courses[item_id] = {"id": course_id, "camera": camera_type}
    
    def start_download(self):
        """Start download process"""
        selected_items = self.course_tree.selection()
        if not selected_items:
            messagebox.showwarning("Warning", "Please select at least one lecture to download")
            return
        
        output_dir = Path(self.output_dir_var.get())
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"Cannot create output directory: {str(e)}")
                return
        
        # Disable download button
        self.download_btn.config(state='disabled', text="Downloading...")
        self.progress.start()
        self.download_status.config(text="Preparing downloads...")
        
        # Start download process in separate thread
        threading.Thread(target=self.download_process, 
                        args=(selected_items, output_dir), daemon=True).start()
    
    def download_process(self, selected_items, output_dir):
        """Download process"""
        if not self.driver:
            self.root.after(0, lambda: messagebox.showerror("Error", "Not logged in"))
            return
        
        try:
            videos_for_subject = {}
            
            # Get videos for each selected course
            for i, item_id in enumerate(selected_items):
                course_info = self.selected_courses[item_id]
                course_name = item_id.split(":")[0]
                
                self.root.after(0, lambda: self.download_status.config(
                    text=f"Fetching videos for {course_name}... ({i+1}/{len(selected_items)})"))
                
                playlists = tum_live.get_video_links_of_subject(
                    self.driver,
                    course_info["id"],
                    course_info["camera"]
                )
                videos_for_subject[course_name] = playlists
            
            # Download videos
            spawned_processes = []
            total_subjects = len(videos_for_subject)
            
            for i, (subject, playlists) in enumerate(videos_for_subject.items()):
                self.root.after(0, lambda s=subject, idx=i: self.download_status.config(
                    text=f"Downloading {s}... ({idx+1}/{total_subjects})"))
                
                subject_folder = Path(output_dir, subject)
                subject_folder.mkdir(exist_ok=True)
                
                spawned_processes += downloader.download_list_of_videos(
                    playlists,
                    subject_folder,
                    self.tmp_dir,
                    self.keep_original_var.get(),
                    self.jump_cut_var.get(),
                    Semaphore(self.max_parallel_downloads)
                )
            
            # Wait for all downloads to complete
            self.root.after(0, lambda: self.download_status.config(text="Finalizing downloads..."))
            for process in spawned_processes:
                process.join()
            
            self.root.after(0, self.download_complete_success)
            
        except Exception as e:
            self.root.after(0, lambda: self.download_complete_error(str(e)))
    
    def download_complete_success(self):
        """Handle successful download completion"""
        self.progress.stop()
        self.download_btn.config(state='normal', text="Download Selected Lectures")
        self.download_status.config(text="Downloads completed successfully!", fg='#28a745')
        messagebox.showinfo("Success", "All downloads completed successfully!")
    
    def download_complete_error(self, error_msg):
        """Handle download error"""
        self.progress.stop()
        self.download_btn.config(state='normal', text="Download Selected Lectures")
        self.download_status.config(text=f"Download failed: {error_msg}", fg='#dc3545')
        messagebox.showerror("Error", f"Download failed: {error_msg}")

def main():
    root = tk.Tk()
    app = TUMLiveDownloaderGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()