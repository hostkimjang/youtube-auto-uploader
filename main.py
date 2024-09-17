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
from datetime import datetime, timedelta
import threading


video_dir_path = f''


#최소 최초 동시업로드 2개 이상해야 현재 감지 로직 작동
MAX_CONCURRENT_UPLOADS = 10
MIN_UPLOAD_BATCH = 2
MAX_RETRIES = 10
RETRY_DELAY = 3600 * 2

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

        # 로그인 완료 대기
        WebDriverWait(browser, 30).until(EC.presence_of_element_located((By.ID, "avatar-btn")))

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
    if not file_paths:
        print("업로드할 파일이 없습니다.")
        return False
    try:
        create_button = WebDriverWait(browser, 30).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#create-icon > ytcp-button-shape > button"))
        )
        create_button.click()

        upload_option = WebDriverWait(browser, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR,
                                        "#text-item-0 > ytcp-ve > tp-yt-paper-item-body > div > div > div > yt-formatted-string"))
        )
        upload_option.click()

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
                    upload_status[title] = {"status": "completed", "timestamp": datetime.now().isoformat()}
                    completed_uploads.append(title)
                    active_uploads.discard(title)
                    status_changed = True
                    save_status(status_file, upload_status)
                elif "취소" in status or "실패" in status:
                    print(f"{title}: 업로드 {status}")
                    upload_status[title] = {"status": "failed", "timestamp": datetime.now().isoformat()}
                    active_uploads.discard(title)
                    status_changed = True
                    save_status(status_file, upload_status)
                elif "일일 업로드 한도 도달" in status:
                    print(f"{title}: 일일 업로드 한도 도달")
                    upload_status[title] = {"status": "limit_reached", "timestamp": datetime.now().isoformat()}
                    save_status(status_file, upload_status)
                    return "limit_reached", list(active_uploads) + list(upload_queue)
                else:
                    print(f"{title}: 업로드 진행 중 - {status}")
                    active_uploads.add(title)

            if not active_uploads and not upload_queue:
                print("모든 파일 업로드 완료")
                return True, []

            time.sleep(5)

        except TimeoutException:
            print("업로드 상태를 확인하는 데 실패했습니다.")
        except Exception as e:
            print(f"예상치 못한 오류 발생: {str(e)}")

    print(f"{max_wait_time}초 동안 업로드가 완료되지 않았습니다.")
    return False, list(active_uploads) + list(upload_queue)


def get_pending_uploads(video_paths, status_file):
    upload_status = load_status(status_file)
    return deque([
        path for path in video_paths
        if os.path.basename(path) not in upload_status or
           upload_status[os.path.basename(path)].get("status") != "completed"
    ])


def wait_with_message(delay, message):
    end_time = datetime.now() + timedelta(seconds=delay)
    event = threading.Event()

    def countdown():
        while datetime.now() < end_time and not event.is_set():
            remaining = (end_time - datetime.now()).total_seconds()
            print(f"\r{message} {remaining:.0f}초 남음...", end="", flush=True)
            event.wait(1)  # 1초마다 업데이트
        print()  # 줄바꿈

    thread = threading.Thread(target=countdown)
    thread.start()

    try:
        event.wait(delay)
    except KeyboardInterrupt:
        print("\n대기가 중단되었습니다.")
        event.set()

    thread.join()


def upload_and_monitor(browser, video_paths, status_file):
    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            upload_queue = get_pending_uploads(video_paths, status_file)

            if len(upload_queue) < MIN_UPLOAD_BATCH:
                print(f"업로드할 파일이 {MIN_UPLOAD_BATCH}개 미만입니다. 프로세스를 종료합니다.")
                break

            browser.get('https://studio.youtube.com/channel/')
            if not navigate_to_content_page(browser):
                print("'콘텐츠' 페이지로 이동 실패. 재시도합니다.")
                retry_count += 1
                wait_with_message(RETRY_DELAY, "재시도 대기 중:")
                continue

            initial_upload_count = max(MIN_UPLOAD_BATCH, min(MAX_CONCURRENT_UPLOADS, len(upload_queue)))
            initial_files = [upload_queue.popleft() for _ in range(initial_upload_count)]

            print("초기 업로드 파일:")
            print([os.path.basename(f) for f in initial_files])

            if upload_files(browser, initial_files):
                initial_file_names = [os.path.basename(f) for f in initial_files]
                if wait_for_upload_start(browser, initial_file_names):
                    result, remaining_files = monitor_and_upload(browser, status_file, upload_queue)
                    if result == "limit_reached":
                        print("일일 업로드 한도에 도달했습니다. 재시도를 준비합니다.")
                        retry_count += 1
                        print(
                            f"재시도 대기 중인 파일: {[os.path.basename(f) for f in get_pending_uploads(video_paths, status_file)]}")
                        wait_with_message(RETRY_DELAY, "일일 한도 도달로 인한 대기:")
                    elif result == True:
                        print("모든 파일 업로드 완료")
                        break
                    else:
                        print("일부 파일 업로드 실패 또는 취소. 재시도를 준비합니다.")
                        retry_count += 1
                        print(
                            f"재시도 대기 중인 파일: {[os.path.basename(f) for f in get_pending_uploads(video_paths, status_file)]}")
                        wait_with_message(RETRY_DELAY, "실패 또는 취소로 인한 대기:")
                else:
                    print("초기 파일 업로드 시작 실패. 재시도를 준비합니다.")
                    retry_count += 1
                    upload_queue.extendleft(reversed(initial_files))
                    wait_with_message(RETRY_DELAY, "업로드 시작 실패로 인한 대기:")
            else:
                print("초기 파일 업로드 실패. 재시도를 준비합니다.")
                retry_count += 1
                upload_queue.extendleft(reversed(initial_files))
                wait_with_message(RETRY_DELAY, "업로드 실패로 인한 대기:")

        except Exception as e:
            print(f"업로드 중 오류 발생: {str(e)}. 재시도를 준비합니다.")
            retry_count += 1
            if retry_count < MAX_RETRIES:
                wait_with_message(RETRY_DELAY, "오류로 인한 대기:")

    if retry_count == MAX_RETRIES:
        print(f"최대 재시도 횟수({MAX_RETRIES})에 도달했습니다. 업로드를 중단합니다.")


def run():
    load_dotenv()
    id = os.getenv('id')
    pw = os.getenv('password')
    chromedriver_autoinstaller.install()
    pprint.pprint(chromedriver_autoinstaller.get_chrome_version())
    options = webdriver.ChromeOptions()

    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.add_experimental_option('detach', True)
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')
    browser = webdriver.Chrome(options=options)

    youtube_login(browser, id, pw)
    upload_and_monitor(browser, get_upload_list(), 'upload_status.json')

if __name__ == '__main__':
    run()
