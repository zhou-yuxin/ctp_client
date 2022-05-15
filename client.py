import time
import logging
import threading
import ctpwrapper as CTP

from ctpwrapper import ApiStructure as CTPStruct

class SpiHelper:

    def __init__(self):
        self._event = threading.Event()
        self._error = None

    def resetCompletion(self):
        self._event.clear()
        self._error = None

    def waitCompletion(self, timeout, operation_name = ""):
        if not self._event.wait(timeout):
            self._error = "%s超时" % operation_name
        if self._error:
            raise TimeoutError(self._error)

    def notifyCompletion(self, error = None):
        self._error = error
        self._event.set()

    def _cvtApiRetToError(self, ret):
        assert(-3 <= ret <= -1)
        return ("网络连接失败", "未处理请求超过许可数", "每秒发送请求数超过许可数")[-ret - 1]

    def checkApiReturn(self, ret):
        if ret != 0:
            raise RuntimeError(self._cvtApiRetToError(ret))

    def checkApiReturnInCallback(self, ret):
        if ret != 0:
            self.notifyCompletion(self._cvtApiRetToError(ret))

    def checkRspInfoInCallback(self, info):
        if not info or info.ErrorID == 0:
            return True
        self.notifyCompletion(info.ErrorMsg)
        return False


class QuoteImpl(SpiHelper, CTP.MdApiPy):

    MAX_TIMEOUT = 10

    def __init__(self, front, flow_dir):
        SpiHelper.__init__(self)
        CTP.MdApiPy.__init__(self)
        self._receiver = None
        self.Create(flow_dir)
        self.RegisterFront(front)
        self.Init()
        self.waitCompletion(self.MAX_TIMEOUT, "登录行情会话")

    def __del__(self):
        self.Release()

    def OnFrontConnected(self):
        logging.info("已连接行情服务器...")
        field = CTPStruct.ReqUserLoginField()
        self.checkApiReturnInCallback(self.ReqUserLogin(field, 0))

    def OnRspUserLogin(self, _, info, req_id, is_last):
        assert(req_id == 0)
        assert(is_last)
        if not self.checkRspInfoInCallback(info):
            return
        logging.info("已登录行情会话...")
        self.notifyCompletion()

    def setReceiver(self, func):
        self._receiver = func

    def subscribe(self, codes):
        self.resetCompletion()
        self.checkApiReturn(self.SubscribeMarketData(codes))
        self.waitCompletion(self.MAX_TIMEOUT, "订阅行情")

    def OnRspSubMarketData(self, field, info, _, is_last):
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        logging.info("已订阅<%s>的行情..." % field.InstrumentID)
        if is_last:
            self.notifyCompletion()

    def OnRtnDepthMarketData(self, field):
        if not self._receiver:
            return
        f = lambda x: None if x > 1.797e+308 else x
        self._receiver({"code": field.InstrumentID, "price": f(field.LastPrice),
                "open": f(field.OpenPrice), "close": f(field.ClosePrice),
                "highest": f(field.HighestPrice), "lowest": f(field.LowestPrice),
                "upper_limit": f(field.UpperLimitPrice), "lower_limit": f(field.LowerLimitPrice),
                "settlement": f(field.SettlementPrice), "volume": field.Volume,
                "turnover": field.Turnover, "open_interest": int(field.OpenInterest),
                "pre_close": f(field.PreClosePrice), "pre_settlement": f(field.PreSettlementPrice),
                "pre_open_interest": int(field.PreOpenInterest),
                "ask1": (f(field.AskPrice1), field.AskVolume1),
                "bid1": (f(field.BidPrice1), field.BidVolume1),
                "ask2": (f(field.AskPrice2), field.AskVolume2),
                "bid2": (f(field.BidPrice2), field.BidVolume2),
                "ask3": (f(field.AskPrice3), field.AskVolume3),
                "bid3": (f(field.BidPrice3), field.BidVolume3),
                "ask4": (f(field.AskPrice4), field.AskVolume4),
                "bid4": (f(field.BidPrice4), field.BidVolume4),
                "ask5": (f(field.AskPrice5), field.AskVolume5),
                "bid5": (f(field.BidPrice5), field.BidVolume5)})

    def unsubscribe(self, codes):
        self.resetCompletion()
        self.checkApiReturn(self.UnSubscribeMarketData(codes))
        self.waitCompletion(self.MAX_TIMEOUT, "取消订阅行情")

    def OnRspUnSubMarketData(self, field, info, _, is_last):
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        logging.info("已取消订阅<%s>的行情..." % field.InstrumentID)
        if is_last:
            self.notifyCompletion()


class TraderImpl(SpiHelper, CTP.TraderApiPy):

    MAX_TIMEOUT = 10

    def __init__(self, front, broker_id, flow_dir, app_id, auth_code, user_id, password):
        SpiHelper.__init__(self)
        CTP.TraderApiPy.__init__(self)
        self._last_query_time = 0
        self._broker_id = broker_id
        self._app_id = app_id
        self._auth_code = auth_code
        self._user_id = user_id
        self._password = password
        self.Create(flow_dir)
        self.RegisterFront(front)
        self.SubscribePrivateTopic(2)   #THOST_TERT_QUICK
        self.SubscribePublicTopic(2)    #THOST_TERT_QUICK
        self.Init()
        self.waitCompletion(self.MAX_TIMEOUT, "登录交易会话")
        del self._app_id, self._auth_code, self._password
        self._map_code_to_exchange = {}
        self.resetCompletion()
        self._limitFrequency()
        self.checkApiReturn(self.ReqQryInstrument(CTPStruct.QryInstrumentField(), 3))
        last_count = 0
        while True:
            try:
                self.waitCompletion(self.MAX_TIMEOUT, "获取所有合约")
                break
            except TimeoutError as e:
                new_count = len(self._map_code_to_exchange)
                if new_count == last_count:
                    raise e
                logging.info("已获取%d个合约..." % new_count)
                last_count = new_count
        self._map_order_to_code = {}
        self.resetCompletion()
        field = CTPStruct.QryOrderField(BrokerID = self._broker_id,
                InvestorID = self._user_id)
        self._limitFrequency()
        self.checkApiReturn(self.ReqQryOrder(field, 4))
        self.waitCompletion(self.MAX_TIMEOUT, "获取所有报单")

    def _limitFrequency(self):
        delta = time.time() - self._last_query_time
        if delta < 1:
            time.sleep(1 - delta)
        self._last_query_time = time.time()

    def __del__(self):
        self.Release()

    def OnFrontConnected(self):
        logging.info("已连接交易服务器...")
        field = CTPStruct.ReqAuthenticateField(BrokerID = self._broker_id,
                AppID = self._app_id, AuthCode = self._auth_code, UserID = self._user_id)
        self.checkApiReturnInCallback(self.ReqAuthenticate(field, 0))

    def OnRspAuthenticate(self, _, info, req_id, is_last):
        assert(req_id == 0)
        assert(is_last)
        if not self.checkRspInfoInCallback(info):
            return
        logging.info("已通过交易终端认证...")
        field = CTPStruct.ReqUserLoginField(BrokerID = self._broker_id,
                UserID = self._user_id, Password = self._password)
        self.checkApiReturnInCallback(self.ReqUserLogin(field, 1))

    def OnRspUserLogin(self, _, info, req_id, is_last):
        assert(req_id == 1)
        assert(is_last)
        if not self.checkRspInfoInCallback(info):
            return
        logging.info("已登录交易会话...")
        field = CTPStruct.SettlementInfoConfirmField(BrokerID = self._broker_id,
                InvestorID = self._user_id)
        self.checkApiReturnInCallback(self.ReqSettlementInfoConfirm(field, 2))

    def OnRspSettlementInfoConfirm(self, _, info, req_id, is_last):
        assert(req_id == 2)
        assert(is_last)
        if not self.checkRspInfoInCallback(info):
            return
        logging.info("已确认结算单...")
        self.notifyCompletion()

    def OnRspQryInstrument(self, field, info, req_id, is_last):
        assert(req_id == 3)
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        if field:
            self._map_code_to_exchange[field.InstrumentID] = field.ExchangeID
        if is_last:
            logging.info("已获取所有合约...")
            self.notifyCompletion()

    def getOrders(self):
        self._orders = {}
        self.resetCompletion()
        field = CTPStruct.QryOrderField(BrokerID = self._broker_id,
                InvestorID = self._user_id)
        self._limitFrequency()
        self.checkApiReturn(self.ReqQryOrder(field, 5))
        self.waitCompletion(self.MAX_TIMEOUT, "获取所有报单")
        return self._orders

    def _gotOrder(self, order):
        (direction, volume) = (int(order.Direction), order.VolumeTotalOriginal)
        assert(direction in (0, 1))
        if order.CombOffsetFlag == '1':     #THOST_FTDC_OFEN_Close
            direction = 1 - direction
            volume = -volume
        direction = "short" if direction else "long"
        #THOST_FTDC_OST_Unknown = a, THOST_FTDC_OST_PartTradedQueueing = 1
        #THOST_FTDC_OST_NoTradeQueueing = 3
        is_active = order.OrderStatus in ('a', '1', '3')
        self._orders[order.OrderSysID] = {"code": order.InstrumentID, "direction": direction,
                "price": order.LimitPrice, "volume": volume, 
                "volume_traded": order.VolumeTraded, "is_active": is_active}

    def OnRspQryOrder(self, field, info, req_id, is_last):
        assert(req_id in (4, 5))
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        if field:
            if req_id == 4:
                self._map_order_to_code[field.OrderSysID] = field.InstrumentID
            elif req_id == 5:
                self._gotOrder(field)
        if is_last:
            logging.info("已获取所有报单...")
            self.notifyCompletion()

    def getPositions(self):
        self._positions = []
        self.resetCompletion()
        field = CTPStruct.QryInvestorPositionField(BrokerID = self._broker_id,
                InvestorID = self._user_id)
        self._limitFrequency()
        self.checkApiReturn(self.ReqQryInvestorPosition(field, 6))
        self.waitCompletion(self.MAX_TIMEOUT, "获取所有持仓")
        return self._positions

    def _gotPosition(self, position):
        code = position.InstrumentID
        if position.PosiDirection == '2':       #THOST_FTDC_PD_Long
            direction = "long"
        elif position.PosiDirection == '3':     #THOST_FTDC_PD_Short
            direction = "short"
        else:
            return
        volume = position.Position
        if volume == 0:
            return
        self._positions.append({"code": code, "direction": direction,
                    "volume": volume, "margin": position.UseMargin,
                    "cost": position.OpenCost})

    def OnRspQryInvestorPosition(self, field, info, req_id, is_last):
        assert(req_id == 6)
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        if field:
            self._gotPosition(field)
        if is_last:
            logging.info("已获取所有持仓...")
            self.notifyCompletion()

    def _order(self, code, direction, volume, price, min_volume):
        if code not in self._map_code_to_exchange:
            raise Exception("合约<%s>不存在！" % code)
        exchange_id = self._map_code_to_exchange[code]
        if direction == "long":
            direction = 0               #THOST_FTDC_D_Buy
        elif direction == "short":
            direction = 1               #THOST_FTDC_D_Sell
        else:
            raise Exception("错误的买卖方向<%s>" % direction)
        if volume != int(volume) or volume == 0:
            raise Exception("交易数量<%s>必须是非零整数" % volume)
        if volume > 0:
            offset_flag = '0'           #THOST_FTDC_OFEN_Open
        else:
            offset_flag = '1'           #THOST_FTDC_OFEN_Close
            volume = -volume
            direction = 1 - direction
        direction = str(direction)
        if min_volume == 0:
            time_cond = '3'             #THOST_FTDC_TC_GFD
            volume_cond = '1'           #THOST_FTDC_VC_AV
        else:
            min_volume = abs(min_volume)
            if min_volume > volume:
                raise Exception("最小成交量<%s>不能超过交易数量<%s>" % (min_volume, volume))
            time_cond = '1'             #THOST_FTDC_TC_IOC
            volume_cond = '2'           #THOST_FTDC_VC_MV
        field = CTPStruct.InputOrderField(BrokerID = self._broker_id,
                InvestorID = self._user_id, ExchangeID = exchange_id, InstrumentID = code,
                Direction = direction, CombOffsetFlag = offset_flag,
                TimeCondition = time_cond, VolumeCondition = volume_cond,
                VolumeTotalOriginal = volume, MinVolume = min_volume,
                CombHedgeFlag = '1',        #THOST_FTDC_HF_Speculation
                ContingentCondition = '1',  #THOST_FTDC_CC_Immediately
                ForceCloseReason = '0',     #THOST_FTDC_FCC_NotForceClose
                OrderPriceType = '2',       #THOST_FTDC_OPT_LimitPrice
                LimitPrice = float(price))
        self.resetCompletion()
        self.checkApiReturn(self.ReqOrderInsert(field, 7))
        self.waitCompletion(self.MAX_TIMEOUT, "录入报单")

    def OnRspOrderInsert(self, field, info, req_id, is_last):
        assert(req_id == 7)
        assert(is_last)
        self.OnErrRtnOrderInsert(field, info)

    def OnErrRtnOrderInsert(self, _, info):
        success = self.checkRspInfoInCallback(info)
        assert(not success)

    def _handleLimit(self, order):
        #THOST_FTDC_OSS_InsertSubmitted = 0, THOST_FTDC_OSS_Accepted = 3
        if order.OrderSubmitStatus not in ('0', '3'):
            self.notifyCompletion(order.StatusMsg)
            return
        if order.OrderStatus == 'a':        #THOST_FTDC_OST_Unknown
            return
        order_id = order.OrderSysID
        if order_id not in self._map_order_to_code:
            logging.info("已提交限价单（单号：<%s>）" % order_id)
            self._order_id = order_id
            self.notifyCompletion()
        elif order.OrderStatus == '5':      #THOST_FTDC_OST_Canceled
            logging.info("已撤销限价单（单号：<%s>）" % order_id)
            self.notifyCompletion()

    def _handleFAK(self, order):
        if order.OrderSubmitStatus != '0' : #THOST_FTDC_OSS_InsertSubmitted
            self.notifyCompletion(order.StatusMsg)
            return
        if order.OrderStatus == 'a':        #THOST_FTDC_OST_Unknown
            return
        #THOST_FTDC_OST_AllTraded = 0, THOST_FTDC_OST_PartTradedNotQueueing = 2
        #THOST_FTDC_OST_NoTradeNotQueueing = 4, THOST_FTDC_OST_Canceled = 5
        if order.OrderStatus not in ('0', '2', '4', '5'):
            self.notifyCompletion(order.StatusMsg)
            return
        logging.info("已执行FAK单，成交量：%d" % order.VolumeTraded)
        self._volume_traded = order.VolumeTraded
        self.notifyCompletion()

    def OnRtnOrder(self, field):
        if field.TimeCondition == '3':      #THOST_FTDC_TC_GFD
            assert(field.MinVolume == 0)
            self._handleLimit(field)
        elif field.TimeCondition == '1':    #THOST_FTDC_TC_IOC
            assert(field.MinVolume > 0)
            self._handleFAK(field)
        else:
            self.notifyCompletion("未知报单类型")
        self._map_order_to_code[field.OrderSysID] = field.InstrumentID

    def orderLimit(self, code, direction, volume, price):
        self._order(code, direction, volume, price, 0)
        return self._order_id

    def orderFAK(self, code, direction, volume, price, min_volume):
        if min_volume == 0:
            min_volume = 1
        self._order(code, direction, volume, price, min_volume)
        return self._volume_traded

    def orderFOK(self, code, direction, volume, price):
        return self.orderFAK(code, direction, volume, price, volume)

    def deleteOrder(self, order_id):
        if order_id not in self._map_order_to_code:
            raise Exception("报单<%s>不存在！" % order_id)
        code = self._map_order_to_code[order_id]
        assert(code in self._map_code_to_exchange)
        exchange_id = self._map_code_to_exchange[code]
        field = CTPStruct.InputOrderActionField(BrokerID = self._broker_id,
                InvestorID = self._user_id, UserID = self._user_id,
                ActionFlag = '0',           #THOST_FTDC_AF_Delete
                ExchangeID = exchange_id, InstrumentID = code,
                OrderSysID = order_id)
        self.resetCompletion()
        self.checkApiReturn(self.ReqOrderAction(field, 8))
        self.waitCompletion(self.MAX_TIMEOUT, "撤销报单")

    def OnRspOrderAction(self, field, info, req_id, is_last):
        assert(req_id == 8)
        assert(is_last)
        self.OnErrRtnOrderAction(field, info)

    def OnErrRtnOrderAction(self, _, info):
        success = self.checkRspInfoInCallback(info)
        assert(not success)


class Client:

    def __init__(self, md_front, td_front, md_flow_dir, td_flow_dir,
            broker_id, app_id, auth_code, user_id, password):
        self._md = QuoteImpl(md_front, md_flow_dir)
        self._td = TraderImpl(td_front, broker_id, td_flow_dir, app_id, auth_code,
                user_id, password)

    def setReceiver(self, func):
        self._md.setReceiver(func)

    def subscribe(self, codes):
        self._md.subscribe(codes)

    def unsubscribe(self, codes):
        self._md.unsubscribe(codes)

    def getOrders(self):
        return self._td.getOrders()

    def getPositions(self):
        return self._td.getPositions()

    def orderLimit(self, code, direction, volume, price):
        return self._td.orderLimit(code, direction, volume, price)

    def orderFAK(self, code, direction, volume, price, min_volume):
        return self._td.orderFAK(code, direction, volume, price, min_volume)

    def orderFOK(self, code, direction, volume, price):
        return self._td.orderFOK(code, direction, volume, price)

    def deleteOrder(self, order_id):
        self._td.deleteOrder(order_id)
