import os
import time
import json
import chromedriver_autoinstaller
from collections import deque
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException
import pprint
from dotenv import load_dotenv
import google_colab_selenium as gs
from selenium.webdriver.chrome.options import Options
video_dir_path = f'/content/drive/MyDrive/0a'


#최소 최초 동시업로드 2개 이상해야 현재 감지 로직 작동
MAX_CONCURRENT_UPLOADS = 3
MIN_UPLOAD_BATCH = 2

def get_upload_list():
    video_extension = ['mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv']
    video_files = []

    for root, dirs, files in os.walk(video_dir_path):
        for file in files:
            if file.split('.')[-1] in video_extension:
                video_files.append(os.path.join(root, file))

    # pprint.pprint(video_files)
    #
    # for i in range(0, len(video_files), batch_size):
    #     batch = video_files[i:i + batch_size]
    #     pprint.pprint(batch)
    #
    #     abs_file_paths = [os.path.abspath(path).replace("\\", "/") for path in batch]
    #     pprint.pprint(abs_file_paths)
    return video_files

def youtube_login(browser, username, password):
    browser.get('https://accounts.google.com/signin/v2/identifier?service=youtube')

    print(f"Current URL: {browser.current_url}")

    try:
        # 사용자 이름 입력
        username_input = WebDriverWait(browser, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='email']")))
        username_input.clear()
        username_input.send_keys(username)
        username_input.send_keys(Keys.RETURN)

        print(f"After username input, URL: {browser.current_url}")

        # 비밀번호 입력 필드가 나타날 때까지 대기
        password_selector = "#password input[type='password']"
        password_input = WebDriverWait(browser, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, password_selector)))

        print(f"Password input found: {password_input.is_displayed()}, {password_input.is_enabled()}")

        # 비밀번호 입력
        password_input.clear()
        password_input.send_keys(password)
        password_input.send_keys(Keys.RETURN)
        print(f"After password input, URL: {browser.current_url}")
        time.sleep(10)
        print(f"\n\nCurrent page source: {browser.page_source}\n\n")
        # 로그인 완료 대기
        WebDriverWait(browser, 300).until(EC.presence_of_element_located((By.ID, "avatar-btn")))

        print(f"Login complete, final URL: {browser.current_url}")

    except TimeoutException:
        print("Timeout occurred while waiting for element")
        print(f"Current page source: {browser.page_source}")
    except StaleElementReferenceException:
        print("Element not found")
        print(f"Current page source: {browser.page_source}")
    except Exception as e:
        print(f"An error occurred: {str(e)}")
        print(f"Current page source: {browser.page_source}")


def load_status(status_file):
    if os.path.exists(status_file):
        with open(status_file, 'r') as f:
            return json.load(f)
    return {}


def save_status(status_file, status):
    with open(status_file, 'w') as f:
        json.dump(status, f, indent=4)


def navigate_to_content_page(browser):
    try:
        # '콘텐츠' 메뉴 항목 클릭
        content_menu = WebDriverWait(browser, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#menu-paper-icon-item-1"))
        )
        content_menu.click()
        print("'콘텐츠' 페이지로 이동 완료")
        return True
    except Exception as e:
        print(f"'콘텐츠' 페이지로 이동 중 오류 발생: {str(e)}")
        return False


def upload_files(browser, file_paths):
    try:
        # '만들기' 버튼 클릭
        create_button = WebDriverWait(browser, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#create-icon > ytcp-button-shape > button"))
        )
        create_button.click()

        # '동영상 업로드' 옵션 선택
        upload_option = WebDriverWait(browser, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                                        "#text-item-0 > ytcp-ve > tp-yt-paper-item-body > div > div > div > yt-formatted-string"))
        )
        upload_option.click()

        # 파일 입력 요소 찾기 및 파일 경로 전송
        file_input = WebDriverWait(browser, 30).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
        )
        file_input.send_keys('\n'.join(file_paths))

        for file_path in file_paths:
            print(f"파일 업로드 시작: {os.path.basename(file_path)}")
        return True
    except Exception as e:
        print(f"파일 업로드 중 오류 발생: {str(e)}")
        return False


def wait_for_upload_start(browser, file_names, timeout=60):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            progress_list = WebDriverWait(browser, 10).until(
                EC.presence_of_element_located((By.ID, "progress-list"))
            )
            list_items = progress_list.find_elements(By.TAG_NAME, "li")

            started_uploads = set()
            for item in list_items:
                title_element = item.find_element(By.CLASS_NAME, "progress-title")
                title = title_element.text
                if title in file_names:
                    started_uploads.add(title)

            if len(started_uploads) == len(file_names):
                return True

            time.sleep(2)
        except Exception as e:
            print(f"업로드 시작 확인 중 오류 발생: {str(e)}")

    print("업로드 시작 대기 시간 초과")
    return False


def monitor_and_upload(browser, status_file, upload_queue, max_wait_time=3600):
    start_time = time.time()
    upload_status = load_status(status_file)
    active_uploads = set()

    while time.time() - start_time < max_wait_time:
        try:
            progress_list = WebDriverWait(browser, 10).until(
                EC.presence_of_element_located((By.ID, "progress-list"))
            )
            list_items = progress_list.find_elements(By.TAG_NAME, "li")

            status_changed = False
            completed_uploads = []
            for item in list_items:
                title_element = item.find_element(By.CLASS_NAME, "progress-title")
                status_element = item.find_element(By.CLASS_NAME, "progress-status-text")
                title = title_element.text
                status = status_element.text

                if "100% 업로드됨" in status or "처리 완료" in status:
                    print(f"{title}: 업로드 완료")
                    upload_status[title] = True
                    completed_uploads.append(title)
                    active_uploads.discard(title)
                    status_changed = True
                    # 각 파일 업로드 완료 시 상태 저장
                    save_status(status_file, upload_status)
                elif "취소" in status or "실패" in status:
                    print(f"{title}: 업로드 {status}")
                    upload_status[title] = False
                    active_uploads.discard(title)
                    status_changed = True
                    # 업로드 실패 시에도 상태 저장
                    save_status(status_file, upload_status)
                elif "일일 업로드 한도 도달" in status:
                    print(f"{title}: 일일 업로드 한도 도달")
                    upload_status[title] = "limit_reached"
                    save_status(status_file, upload_status)
                    return "limit_reached"
                else:
                    print(f"{title}: 업로드 진행 중 - {status}")
                    active_uploads.add(title)

            # 새로운 파일 업로드 시작
            available_slots = MAX_CONCURRENT_UPLOADS - len(active_uploads)
            if available_slots >= MIN_UPLOAD_BATCH and upload_queue and len(completed_uploads) > 0:
                new_files = []
                for _ in range(min(available_slots, MIN_UPLOAD_BATCH)):
                    if upload_queue:
                        new_file = upload_queue.popleft()
                        new_files.append(new_file)
                if new_files:
                    if upload_files(browser, new_files):
                        new_file_names = [os.path.basename(f) for f in new_files]
                        if wait_for_upload_start(browser, new_file_names):
                            active_uploads.update(new_file_names)
                        else:
                            print("새 파일 업로드 시작 실패")
                            upload_queue.extendleft(reversed(new_files))

            if not active_uploads and not upload_queue:
                print("모든 파일 업로드 완료")
                return True

            time.sleep(3)

        except TimeoutException:
            print("업로드 상태를 확인하는 데 실패했습니다.")
        except Exception as e:
            print(f"예상치 못한 오류 발생: {str(e)}")

    print(f"{max_wait_time}초 동안 업로드가 완료되지 않았습니다.")
    return False


def upload_and_monitor(browser, video_dir_paths, status_file, retry_delay=3600):
    upload_status = load_status(status_file)
    upload_queue = deque([path for path in video_dir_paths if
                          os.path.basename(path) not in upload_status or not upload_status[os.path.basename(path)]])

    try:
        browser.get('https://studio.youtube.com/channel/')
        if not navigate_to_content_page(browser):
            print("'콘텐츠' 페이지로 이동 실패. 업로드를 중단합니다.")
            return

        # 초기 업로드 시작
        initial_upload_count = min(MAX_CONCURRENT_UPLOADS, len(upload_queue))
        initial_files = [upload_queue.popleft() for _ in range(initial_upload_count)]

        print("초기 업로드 파일:")
        print(initial_files)

        if upload_files(browser, initial_files):
            initial_file_names = [os.path.basename(f) for f in initial_files]
            if wait_for_upload_start(browser, initial_file_names):
                result = monitor_and_upload(browser, status_file, upload_queue)
                if result == "limit_reached":
                    print(f"일일 업로드 한도에 도달했습니다. {retry_delay / 3600}시간 후 재시도합니다.")
                    time.sleep(retry_delay)
                    # 재시도 로직 추가 필요
                elif result == True:
                    print("모든 파일 업로드 완료")
                else:
                    print("일부 파일 업로드 실패 또는 취소. 확인이 필요합니다.")
            else:
                print("초기 파일 업로드 시작 실패")
        else:
            print("초기 파일 업로드 실패")

    except Exception as e:
        print(f"업로드 중 오류 발생: {str(e)}")
        save_status(status_file, upload_status)


def run():
    load_dotenv()
    id = 'hoangqviey'
    pw = 'Viet02112001'
    chromedriver_autoinstaller.install()
    pprint.pprint(chromedriver_autoinstaller.get_chrome_version())
    options = webdriver.ChromeOptions()
    # Add extra options
        # Set user data directory to save the profile
    options.add_argument("--window-size=1920,1080")  # Set the window size
    options.add_argument("--disable-infobars")  # Disable the infobars
    options.add_argument("--disable-popup-blocking")  # Disable pop-ups
    options.add_argument("--ignore-certificate-errors")  # Ignore certificate errors
    options.add_argument("--disable-blink-features=AutomationControlled") 

    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.add_experimental_option('detach', True)
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')
    browser = gs.Chrome(options=options)

    youtube_login(browser, id, pw)
    upload_and_monitor(browser, get_upload_list(), 'upload_status.json')

if __name__ == '__main__':
    run()
