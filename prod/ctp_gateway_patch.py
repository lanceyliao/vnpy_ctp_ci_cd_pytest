from pathlib import Path

from vnpy.trader.utility import get_folder_path
from vnpy.trader.object import SubscribeRequest
from vnpy_ctp import CtpGateway as BaseCtpGateway
from vnpy_ctp.gateway.ctp_gateway import Exchange, CHINA_TZ, datetime, TickData, adjust_price, CtpMdApi as BaseMdApi


class CtpGateway(BaseCtpGateway):
    """继承和扩展CTP网关"""

    def __init__(self, event_engine, gateway_name: str) -> None:
        """构造函数"""
        super().__init__(event_engine, gateway_name)
        
        # 重写行情API
        self.md_api = MdApi(self)

    def connect(self, setting: dict) -> None:
        """连接交易接口"""
        userid: str = setting["用户名"]
        password: str = setting["密码"]
        brokerid: str = setting["经纪商代码"]
        td_address: str = setting["交易服务器"]
        md_address: str = setting["行情服务器"]
        appid: str = setting["产品名称"]
        auth_code: str = setting["授权编码"]

        # 扩展交易服务器地址
        td_addresses = expand_domain_template(td_address)
        # 扩展行情服务器地址
        md_addresses = expand_domain_template(md_address)

        # 添加TCP前缀
        for i, addr in enumerate(td_addresses):
            if (
                (not addr.startswith("tcp://"))
                and (not addr.startswith("ssl://"))
                and (not addr.startswith("socks"))
            ):
                td_addresses[i] = "tcp://" + addr

        for i, addr in enumerate(md_addresses):
            if (
                (not addr.startswith("tcp://"))
                and (not addr.startswith("ssl://"))
                and (not addr.startswith("socks"))
            ):
                md_addresses[i] = "tcp://" + addr

        # self.td_api.connect(td_addresses, userid, password, brokerid, auth_code, appid)
        self.md_api.connect(md_addresses, userid, password, brokerid)

        # self.init_query()

    def close(self) -> None:
        """关闭接口"""
        # self.td_api.close()
        self.md_api.close()

class MdApi(BaseMdApi):
    """继承和扩展行情API"""

    def __init__(self, gateway: "CtpGateway") -> None:
        """构造函数"""
        super().__init__(gateway)

        # 添加合约-交易所映射字典
        self.symbol_exchange_map: dict[str, Exchange] = {}

    def connect(self, addresses: list[str], userid: str, password: str, brokerid: str) -> None:
        """连接服务器"""
        self.userid = userid
        self.password = password
        self.brokerid = brokerid

        # 禁止重复发起连接，会导致异常崩溃
        if not self.connect_status:
            path: Path = get_folder_path(self.gateway_name.lower())
            self.createFtdcMdApi((str(path) + "\\Md").encode("GBK"))

            # 注册多个行情服务器地址，底层使用第一个正常连接
            print(addresses)
            for address in addresses:
                self.registerFront(address)

            self.init()

            self.connect_status = True

    def onRtnDepthMarketData(self, data: dict) -> None:
        """行情数据推送"""
        # 过滤没有时间戳的异常行情数据
        if not data["UpdateTime"]:
            return

        # 过滤还没有收到合约数据前的行情推送
        symbol: str = data["InstrumentID"]
        # contract: ContractData = symbol_contract_map.get(symbol, None)
        # if not contract:
        #     return
        exchange: Exchange = self.symbol_exchange_map.get(symbol, None)
        if not exchange:
            return

        # 对大商所的交易日字段取本地日期
        # if not data["ActionDay"] or contract.exchange == Exchange.DCE:
        if not data["ActionDay"] or exchange == Exchange.DCE:
            date_str: str = self.current_date
        else:
            date_str: str = data["ActionDay"]

        timestamp: str = f"{date_str} {data['UpdateTime']}.{data['UpdateMillisec']}"
        dt: datetime = datetime.strptime(timestamp, "%Y%m%d %H:%M:%S.%f")
        dt: datetime = dt.replace(tzinfo=CHINA_TZ)

        tick: TickData = TickData(
            symbol=symbol,
            # exchange=contract.exchange,
            exchange=exchange,
            datetime=dt,
            # name=contract.name,
            name=symbol,  # 没有合约信息时，name 直接使用 symbol
            volume=data["Volume"],
            turnover=data["Turnover"],
            open_interest=data["OpenInterest"],
            last_price=adjust_price(data["LastPrice"]),
            limit_up=data["UpperLimitPrice"],
            limit_down=data["LowerLimitPrice"],
            open_price=adjust_price(data["OpenPrice"]),
            high_price=adjust_price(data["HighestPrice"]),
            low_price=adjust_price(data["LowestPrice"]),
            pre_close=adjust_price(data["PreClosePrice"]),
            bid_price_1=adjust_price(data["BidPrice1"]),
            ask_price_1=adjust_price(data["AskPrice1"]),
            bid_volume_1=data["BidVolume1"],
            ask_volume_1=data["AskVolume1"],
            gateway_name=self.gateway_name
        )

        if data["BidVolume2"] or data["AskVolume2"]:
            tick.bid_price_2 = adjust_price(data["BidPrice2"])
            tick.bid_price_3 = adjust_price(data["BidPrice3"])
            tick.bid_price_4 = adjust_price(data["BidPrice4"])
            tick.bid_price_5 = adjust_price(data["BidPrice5"])

            tick.ask_price_2 = adjust_price(data["AskPrice2"])
            tick.ask_price_3 = adjust_price(data["AskPrice3"])
            tick.ask_price_4 = adjust_price(data["AskPrice4"])
            tick.ask_price_5 = adjust_price(data["AskPrice5"])

            tick.bid_volume_2 = data["BidVolume2"]
            tick.bid_volume_3 = data["BidVolume3"]
            tick.bid_volume_4 = data["BidVolume4"]
            tick.bid_volume_5 = data["BidVolume5"]

            tick.ask_volume_2 = data["AskVolume2"]
            tick.ask_volume_3 = data["AskVolume3"]
            tick.ask_volume_4 = data["AskVolume4"]
            tick.ask_volume_5 = data["AskVolume5"]

        self.gateway.on_tick(tick)

    def subscribe(self, req: SubscribeRequest) -> None:
        """订阅行情"""
        if self.login_status:
            self.subscribeMarketData(req.symbol)
            # 保存合约和交易所的映射关系
            self.symbol_exchange_map[req.symbol] = req.exchange
        self.subscribed.add(req.symbol)

def expand_domain_template(address: str) -> list[str]:
    """将域名模板扩展为实际地址列表
    支持以下格式：
    1. 单个地址: tcp://127.0.0.1:8888
    2. 逗号分隔: tcp://127.0.0.1:8888,tcp://127.0.0.2:8888
    3. 范围模板: ctp1-front{1,3/5,8,10/18}.citicsf.com
    """
    import re

    # 使用正则表达式匹配范围模板 {1,3/5,8,10/18}
    pattern = r'{([0-9,/]+)}'
    match = re.search(pattern, address)

    if match:
        template = address
        ranges_str = match.group(1)  # 提取括号内的内容

        # 解析范围并收集所有数字
        numbers = set()
        for part in ranges_str.split(','):
            if '/' in part:
                start, end = map(int, part.split('/'))
                numbers.update(range(start, end + 1))
            else:
                numbers.add(int(part))

        # 替换模板中的整个匹配部分（包括花括号）
        addresses = [template.replace(match.group(0), str(i)) for i in sorted(numbers)]
        return addresses

    # 处理逗号分隔的地址列表
    elif "," in address:
        return [addr.strip() for addr in address.split(",")]

    # 处理单个地址
    else:
        return [address]