from time import sleep
from typing import Dict, List
from selenium import webdriver
from selenium.webdriver.firefox.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import os
import re

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

def get_courses(tum_username: str, tum_password: str) -> tuple[WebDriver, List[tuple[str, str]]]:
    driver = login(tum_username, tum_password)
    courses = [] 
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "my-courses"))
        )
    except TimeoutException:
        print("No 'My Courses' section found.")
        return (driver, courses)  # empty list
    
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
    
    course_names_only= [course[0] for course in courses]
    print('\n'.join(course_names_only))
    return (driver,courses)

def get_lecture_urls(driver: WebDriver, courses: List[tuple[str, str]]) -> Dict[str, List[tuple[str, str]]]:
    ''' return all lecture links for a all courses
        {
            "Course Name": [
                (lecture_id, url),
                ...
            ],
            ...
        }
    '''
    lectures: Dict[str, List[tuple[str, str]]] = {}
    for course_name, course_url in courses:
        driver.get(course_url)
        sleep(1)
        page_html = driver.page_source
        pattern = r'<a\s+[^>]*:href="course\.WatchURL\(vod\.ID\)"[^>]*href="(/w/[^"]+/(\d+))"'
        matches = re.findall(pattern, page_html)
        for href, vod_id in matches:
            full_url = f"https://live.rbg.tum.de{href}"
            lec_id= href.split('/')[-1].replace('"','')
            lectures.setdefault(course_name, []).append((lec_id, full_url))
    return lectures

def get_playlist_url(driver : WebDriver, lectures: Dict[str, List[tuple[str, str]]], stream_type: str = "COMB") -> Dict[str, List[tuple[str, str]]] :
    # stream_type: "COMB", "CAM", or "PRES"
    updated_lectures: Dict[str, List[tuple[str, str]]] = {}
    for course_name, lec_list in lectures.items():
        updated_lectures[course_name] = []
        for lec_id, lec_url in lec_list:
            if stream_type.upper() != "COMB":
                url = f"{lec_url}/{stream_type.upper()}"
            else: 
                url = lec_url
            driver.get(url)
            sleep(1)
            page_source = driver.page_source
            # get the Lecture title 
            title_match = re.search(r'<h1 [^>]*@titleupdate\.window[^>]*>(.*?)</h1>', page_source, re.DOTALL)
            if title_match :
                lecture_name = title_match.group(1).strip()
            else :
                lecture_name = lec_id  # fallback
            # get the m3u8 playlist
            m3u8_matches = re.findall(r'<source\s+src="([^"]+\.m3u8[^"]*)"', page_source)
            if not m3u8_matches:
                raise ValueError(f"No m3u8 found for {lecture_name}")
            m3u8_url = m3u8_matches[0] # first match
            updated_lectures[course_name].append((lecture_name, m3u8_url))

    return updated_lectures
