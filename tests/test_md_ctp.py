import os
import sys
from datetime import datetime
from time import sleep

# 添加项目根目录到Python路径
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import pytest
from vnpy.event import EventEngine, Event
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_TICK
from vnpy.trader.object import TickData, SubscribeRequest, Exchange
from vnpy.trader.utility import load_json

from prod.ctp_gateway_patch import CtpGateway


@pytest.fixture(scope="module")
def event_engine():
    """创建事件引擎"""
    engine = EventEngine()
    yield engine
    engine.stop()

@pytest.fixture(scope="module")
def main_engine(event_engine):
    """创建主引擎"""
    main_engine = MainEngine(event_engine)
    yield main_engine
    main_engine.close()

@pytest.fixture(scope="module")
def gateway(main_engine):
    """创建并连接CTP网关"""
    gateway = main_engine.add_gateway(CtpGateway)
    
    # 连接CTP
    setting = load_json("connect_ctp_7_24.json")
    main_engine.connect(setting, "CTP")
    
    # 等待登录成功
    for i in range(20):
        if gateway.md_api.login_status:
            print("行情接口登录成功")
            break
        sleep(1)
    else:
        pytest.fail("CTP行情接口登录失败")
    
    yield gateway

def test_gateway_connection(gateway):
    """测试CTP网关连接"""
    assert gateway.md_api.login_status, "行情接口未登录"

def test_market_data_subscription(main_engine, gateway):
    """测试行情订阅"""
    # 标记是否收到行情
    received_tick = False
    
    def on_tick(event: Event):
        nonlocal received_tick
        tick: TickData = event.data
        print(f"收到行情: {tick.symbol} - {tick.exchange}")
        received_tick = True
    
    main_engine.event_engine.register(EVENT_TICK, on_tick)
    
    try:
        # 订阅合约
        symbols = ["au2504", "sc2504"]  # 活跃合约
        exchanges = [Exchange.SHFE, Exchange.INE]
        
        for symbol, exchange in zip(symbols, exchanges):
            req = SubscribeRequest(symbol=symbol, exchange=exchange)
            main_engine.subscribe(req, "CTP")
            print(f"订阅合约: {symbol}.{exchange}")
            
        # 等待行情数据
        start = datetime.now()
        
        # 等待10秒接收行情
        while (datetime.now() - start).seconds < 10:
            if received_tick:
                print("成功接收到行情数据")
                return
            sleep(0.5)
            print(".", end="", flush=True)
            
        pytest.fail("未收到任何行情数据")
            
    finally:
        main_engine.event_engine.unregister(EVENT_TICK, on_tick)
