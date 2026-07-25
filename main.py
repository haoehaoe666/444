import json
import time
import datetime
import argparse
import os
import logging

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

from utils import reserve, get_user_credentials

# 保留原有的 lambda 函数供其他函数兼容使用
get_current_time = lambda action: (
    time.strftime("%H:%M:%S", time.localtime(time.time() + 8 * 3600))
    if action
    else time.strftime("%H:%M:%S", time.localtime(time.time()))
)
get_current_dayofweek = lambda action: (
    time.strftime("%A", time.localtime(time.time() + 8 * 3600))
    if action
    else time.strftime("%A", time.localtime(time.time()))
)

def get_bj_datetime(action):
    """获取当前北京时间的 datetime 对象，统一处理 GitHub Actions(UTC) 和本地运行(本地时区)"""
    if action:
        return datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    else:
        return datetime.datetime.now()

SLEEPTIME = 0.2  # 每次抢座的间隔
ENDTIME = "20:01:00"  # 兼容保留，但在 main 中使用 datetime 进行精确控制

ENABLE_SLIDER = True  # 是否有滑块验证
MAX_ATTEMPT = 3  # 最大尝试次数
RESERVE_NEXT_DAY = False  # 预约明天而不是今天的


def main(users, action=False):
    logging.info(
        f"Global settings: \nSLEEPTIME: {SLEEPTIME}\nENABLE_SLIDER: {ENABLE_SLIDER}\nRESERVE_NEXT_DAY: {RESERVE_NEXT_DAY}"
    )
    
    # 1. 第一步：解析账号密码，增加 .strip() 增强容错，防止 secrets 中不小心带了空格
    usernames, passwords = None, None
    if action:
        raw_usernames, raw_passwords = get_user_credentials(action)
        usernames = [u.strip() for u in raw_usernames.split(",")]
        passwords = [p.strip() for p in raw_passwords.split(",")]
        if len(usernames) != len(users):
            raise Exception("user number should match the number of config")

    current_dayofweek = get_current_dayofweek(action)
    active_tasks = []

    # 2. 第二步：提前进行所有账号的登录，保存 Session
    logging.info("=== 阶段 1：提前初始化并登录账号 ===")
    for index, user in enumerate(users):
        username, password, times, roomid, seatid, daysofweek = user.values()
        if action:
            username, password = usernames[index], passwords[index]

        if current_dayofweek not in daysofweek:
            logging.info(f"[{username}] 今天未设置抢座，跳过。")
            continue

        logging.info(f"[{username}] 初始化并尝试登录获取 Cookie...")
        s = reserve(
            sleep_time=SLEEPTIME,
            max_attempt=MAX_ATTEMPT,
            enable_slider=ENABLE_SLIDER,
            reserve_next_day=RESERVE_NEXT_DAY,
        )
        s.get_login_status()
        s.login(username, password)
        s.requests.headers.update({"Host": "office.chaoxing.com"})
        
        # 将准备就绪的请求体保存到任务列表中
        active_tasks.append({
            "username": username,
            "session": s,
            "times": times,
            "roomid": roomid,
            "seatid": seatid,
            "success": False
        })

    if not active_tasks:
        logging.info("今日没有需要执行的抢座任务，程序结束。")
        return

    # 3. 第三步：进入精准等待循环
    logging.info("=== 阶段 2：时间校验与阻塞等待 ===")
    now = get_bj_datetime(action)
    target_start = now.replace(hour=19, minute=59, second=59, microsecond=0)
    target_end = now.replace(hour=20, minute=1, second=0, microsecond=0)
    
    run_once = False
    if now >= target_end:
        logging.info(f"当前时间 {now.strftime('%H:%M:%S')} 已超过 20:01:00，启动单次补刷模式！")
        run_once = True
    elif now < target_start:
        logging.info(f"当前时间 {now.strftime('%H:%M:%S')}，预热完毕，等待到达 19:59:57...")
        while True:
            now = get_bj_datetime(action)
            if now >= target_start:
                logging.info(f"到达预定时间: {now.strftime('%H:%M:%S')}，开始请求！")
                break
            time.sleep(0.1) 
    else:
        logging.info(f"当前时间 {now.strftime('%H:%M:%S')} 处于黄金窗口，立即开始抢座！")

    # 4. 第四步：高频并发提交
    logging.info("=== 阶段 3：执行抢座提交 ===")
    attempt_times = 0
    while True:
        now = get_bj_datetime(action)
        
        # 退出条件 A：正常模式下超过 20:01 结束
        if not run_once and now >= target_end:
            logging.info("时间已过 20:01:00，抢座窗口结束。")
            break

        attempt_times += 1
        all_success = True

        for task in active_tasks:
            if task["success"]:
                continue # 已成功的账号不再重复提交
            
            username = task["username"]
            logging.info(f"----------- [{username}] 尝试第 {attempt_times} 次提交，座位: {task['seatid']} -----------")
            
            # 核心优化：只调用 submit()，不再走 login()
            suc = task["session"].submit(task["times"], task["roomid"], task["seatid"], action)
            task["success"] = suc
            
            if not suc:
                all_success = False

        logging.info(f"当前轮数 {attempt_times}, 时间 {now.strftime('%H:%M:%S')}")

        # 退出条件 B：全部抢座成功
        if all_success:
            logging.info("🎉 所有账号均预约成功！")
            break
            
        # 退出条件 C：单次补刷模式结束
        if run_once:
            logging.info("八点零一后的单次执行模式已完成，自动退出。")
            break

        time.sleep(SLEEPTIME)

# ==========================================
# 下方原有 debug, get_roomid 函数保持完全不变
# ==========================================

def debug(users, action=False):
    logging.info(
        f"Global settings: \nSLEEPTIME: {SLEEPTIME}\nENDTIME: {ENDTIME}\nENABLE_SLIDER: {ENABLE_SLIDER}\nRESERVE_NEXT_DAY: {RESERVE_NEXT_DAY}"
    )
    suc = False
    logging.info(f" Debug Mode start! , action {'on' if action else 'off'}")
    if action:
        usernames, passwords = get_user_credentials(action)
    current_dayofweek = get_current_dayofweek(action)
    for index, user in enumerate(users):
        username, password, times, roomid, seatid, daysofweek = user.values()
        if type(seatid) == str:
            seatid = [seatid]
        if action:
            username, password = (
                usernames.split(",")[index],
                passwords.split(",")[index],
            )
        if current_dayofweek not in daysofweek:
            logging.info("Today not set to reserve")
            continue
        logging.info(f"----------- {username} -- {times} -- {seatid} try -----------")
        s = reserve(
            sleep_time=SLEEPTIME,
            max_attempt=MAX_ATTEMPT,
            enable_slider=ENABLE_SLIDER,
            reserve_next_day=RESERVE_NEXT_DAY,
        )
        s.get_login_status()
        s.login(username, password)
        s.requests.headers.update({"Host": "office.chaoxing.com"})
        suc = s.submit(times, roomid, seatid, action)
        if suc:
            return


def get_roomid(args1, args2):
    username = input("请输入用户名：")
    password = input("请输入密码：")
    s = reserve(
        sleep_time=SLEEPTIME,
        max_attempt=MAX_ATTEMPT,
        enable_slider=ENABLE_SLIDER,
        reserve_next_day=RESERVE_NEXT_DAY,
    )
    s.get_login_status()
    s.login(username=username, password=password)
    s.requests.headers.update({"Host": "office.chaoxing.com"})
    encode = input("请输入deptldEnc：")
    s.roomid(encode)


if __name__ == "__main__":
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    parser = argparse.ArgumentParser(prog="Chao Xing seat auto reserve")
    parser.add_argument("-u", "--user", default=config_path, help="user config file")
    parser.add_argument(
        "-m",
        "--method",
        default="reserve",
        choices=["reserve", "debug", "room"],
        help="for debug",
    )
    parser.add_argument(
        "-a",
        "--action",
        action="store_true",
        help="use --action to enable in github action",
    )
    args = parser.parse_args()
    func_dict = {"reserve": main, "debug": debug, "room": get_roomid}
    with open(args.user, "r+") as data:
        usersdata = json.load(data)["reserve"]
    func_dict[args.method](usersdata, args.action)
