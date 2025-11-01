from time import sleep
from typing import Dict, List, Tuple
from selenium import webdriver
from selenium.webdriver.firefox.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import argparse
import os
import re
import util

def login(tum_username: str, tum_password: str) -> WebDriver:
    driver_options = webdriver.FirefoxOptions()
    if str(os.getenv('HEADLESS', 'true')) in ("1", "true", "yes", "on"):
        driver_options.add_argument("--headless")
    if os.getenv('NO-SANDBOX') == '1':
        driver_options.add_argument("--no-sandbox")
    driver = webdriver.Firefox(options=driver_options)

    if tum_username and tum_password:
        driver.get("https://live.rbg.tum.de/login")
        driver.find_element(By.XPATH, "/html/body/main/section/article/div/button").click()
        driver.find_element(By.ID, "username").send_keys(tum_username)
        driver.find_element(By.ID, "password").send_keys(tum_password)
        driver.find_element(By.ID, "username").submit()
        sleep(2)
        if "Couldn't log in. Please double check your credentials." in driver.page_source:
            driver.close()
            raise argparse.ArgumentTypeError("Username or password incorrect")
    driver.get("https://live.rbg.tum.de/")
    return driver

def get_courses(tum_username: str, tum_password: str, queue: Dict[str, List[Tuple[str, str]]]):
    driver = login(tum_username, tum_password)
    courses = [] 
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "my-courses"))
        )
    except TimeoutException:
        print("No 'My Courses' section found.")
        return courses  # empty list
    
    try:
        section = driver.find_element(By.ID, "my-courses")
        course_links = section.find_elements(By.CSS_SELECTOR, "a.title")
        print(f"Found {len(course_links)} courses in 'My Courses'.")

        for a in course_links:
            try:
                name = a.text.strip()
                href = a.get_attribute("href")
                if name and href:
                    # Some hrefs are relative (like '?year=2025...'), prepending base URL
                    if href.startswith("?") or href.startswith("/"):
                        href = f"https://live.rbg.tum.de{href}"
                    courses.append((name, href))
            except Exception as e:
                print(f"Skipping a course due to parse error: {e}")
    except NoSuchElementException:
        print("'My Courses' section missing or structure changed.")
    return courses

def get_course_lectures(driver: WebDriver, course_url: str) -> List[Tuple[str, str]]:
    """Open a course page and return [(lecture_title, lecture_url), ...]"""
    

def get_subjects(driver: WebDriver) -> List[Tuple[str, str]]:
    links_on_page = driver.find_elements(By.XPATH, '//*[@id="my-courses"]/article/section[1]/a')
    




    video_urls: List[str] = []
    for link in links_on_page:
        link_url = link.get_attribute("href")
        if link_url and "https://live.rbg.tum.de/w/" in link_url:
            video_urls.append(link_url)

    video_urls = [url for url in video_urls if ("/CAM" not in url and "/PRES" not in url and "/chat" not in url)]
    video_urls = list(dict.fromkeys(video_urls))  # deduplicate
    if not video_urls:
        return []  # Empty lecture series

    sort_order = driver.find_element(By.ID, "sort_order_button").text

    video_playlists: List[Tuple[str, str]] = []
    for video_url in video_urls:
        driver.get(video_url + "/" + camera_type)
        sleep(2)
        filename = driver.find_element(By.XPATH, "//h1").text.strip()
        if not ("Starts in more than a day" or "Stream is due") in driver.page_source:
            playlist_url = get_playlist_url(driver.page_source)
            video_playlists.append((filename, playlist_url))

    if "ASC" in sort_order:
        video_playlists.reverse()

    return video_playlists


def get_playlist_url(source: str) -> str:
    playlist_extracted_match = re.search(r"(https://\S+?/playlist\.m3u8.*?)[\'|\"]", source)
    if not playlist_extracted_match:
        raise Exception("Could not extract playlist URL from TUM-live! Page source:\n" + source)
    playlist_url = playlist_extracted_match.group(1)
    return playlist_url


