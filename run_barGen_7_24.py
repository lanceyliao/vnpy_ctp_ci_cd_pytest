import multiprocessing
import os
import signal
import sys
from datetime import time, datetime
from logging import INFO
from time import sleep

from vnpy.event import Event
from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_ACCOUNT, EVENT_POSITION, EVENT_TICK
from vnpy.trader.object import SubscribeRequest, Exchange
from vnpy.trader.setting import SETTINGS
from vnpy.trader.utility import load_json
from vnpy_ctastrategy.base import EVENT_CTA_LOG

from prod.ctp_gateway_patch import CtpGateway

# 提前15分钟开启行情录制
trading_hours = [(time(8, 30), time(15, 15)), (time(20, 30), time.max), (time.min, time(2, 45))]
connect_filename = 'connect_ctp_7_24.json'

SETTINGS["log.file"] = True
SETTINGS["log.active"] = True
SETTINGS["log.level"] = INFO
SETTINGS["log.console"] = True


def check_trading_period() -> bool:
    """检查是否在交易时段"""
    return True  # test

    current_time = datetime.now().time()
    for start, end in trading_hours:
        if start <= current_time <= end:
            return True
    return False


class SimnowApp:
    """Simnow应用"""

    def __init__(self):
        """构造函数"""
        self.event_engine = EventEngine()
        self.main_engine = MainEngine(self.event_engine)

        self.register_event()
        self.init_engines()
        self.init_strategies()

        # 添加信号处理
        signal.signal(signal.SIGTERM, self.handle_signal)

    def init_engines(self) -> None:
        """初始化引擎"""
        # 添加CTP网关
        self.ctp_gateway = self.main_engine.add_gateway(CtpGateway)
        self.write_log("接口添加成功")

        # 注册日志事件监听
        log_engine = self.main_engine.get_engine("log")
        self.event_engine.register(EVENT_CTA_LOG, log_engine.process_log_event)
        self.write_log("注册日志事件监听")

        # 连接CTP接口
        setting = load_json(connect_filename)
        self.main_engine.connect(setting, "CTP")
        self.write_log("连接CTP接口")

    def register_event(self):
        """注册事件监听"""
        self.event_engine.register(EVENT_ACCOUNT, self.process_event)
        self.event_engine.register(EVENT_POSITION, self.process_event)
        self.event_engine.register(EVENT_TICK, self.process_event)

    def process_event(self, event: Event):
        """处理账户事件"""
        self.main_engine.write_log(f"{event.type} Update: {event.data}")

    def write_log(self, msg: str):
        func_name = sys._getframe(1).f_code.co_name
        class_name = self.__class__.__name__
        formatted_msg = f"[{class_name}.{func_name}] {msg}"
        self.main_engine.write_log(formatted_msg)

    def init_strategies(self):
        """初始化策略"""
        while not self.ctp_gateway.md_api.login_status:
            self.write_log(f"等待CTP行情接口连接")
            sleep(1)
        self.write_log(f"订阅行情")
        vt_symbols = ["au2504.SHFE", "sc2504.INE"]
        for vt_symbol in vt_symbols:
            symbol, exchange = vt_symbol.split(".")
            req: SubscribeRequest = SubscribeRequest(symbol=symbol, exchange=Exchange(exchange))
            self.ctp_gateway.subscribe(req)

    def run(self):
        """运行应用"""
        self.write_log("应用已启动")
        while True:
            sleep(1)

    def close(self):
        """关闭应用"""
        self.write_log("正在关闭应用...")
        self.main_engine.close()
        self.write_log("应用关闭完成")

    def handle_signal(self, signum, frame):
        """处理进程信号"""
        self.write_log(f"收到信号 {signum}，准备关闭应用...")
        self.close()
        sys.exit(0)


def run_child():
    """子进程运行函数"""
    app = SimnowApp()
    app.run()


def run_parent():
    """父进程运行函数"""
    print("启动CTA策略守护父进程")
    child_process = None

    while True:
        trading = check_trading_period()

        if trading and child_process is None:
            print("启动子进程")
            child_process = multiprocessing.Process(target=run_child)
            child_process.start()
            print("子进程启动成功")

        elif not trading and child_process is not None:
            if child_process.is_alive():
                # 发送系统退出信号
                print("非交易时段，发送退出信号")
                os.kill(child_process.pid, signal.SIGTERM)  # 发送终止信号

                # 给予一定时间让子进程完成清理
                child_process.join(timeout=30)

                # 如果子进程仍然存活，才使用terminate强制终止
                if child_process.is_alive():
                    print("子进程未能正常关闭，强制终止")
                    child_process.terminate()
                    child_process.join()

            child_process = None
            print("子进程关闭成功")

        sleep(5)


if __name__ == "__main__":
    run_parent()
