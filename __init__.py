import os
import json
import time
import logging
import threading
import ctpwrapper as CTP
import ctpwrapper.ApiStructure as CTPStruct

MAX_TIMEOUT = 10
DATA_DIR = ".ctp_client_data/"

FILTER = lambda x: None if x > 1.797e+308 else x

class SpiHelper:

    def __init__(self):
        self._event = threading.Event()
        self._error = None

    def resetCompletion(self):
        self._event.clear()
        self._error = None

    def waitCompletion(self, operation_name = ""):
        if not self._event.wait(MAX_TIMEOUT):
            raise TimeoutError("%s超时" % operation_name)
        if self._error:
            raise RuntimeError(self._error)

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

    def __init__(self, front):
        SpiHelper.__init__(self)
        CTP.MdApiPy.__init__(self)
        self._receiver = None
        flow_dir = DATA_DIR + "md_flow/"
        os.makedirs(flow_dir, exist_ok = True)
        self.Create(flow_dir)
        self.RegisterFront(front)
        self.Init()
        self.waitCompletion("登录行情会话")

    def __del__(self):
        logging.info("已登出行情服务器...")

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
        old_func = self._receiver
        self._receiver = func
        return old_func

    def subscribe(self, codes):
        self.resetCompletion()
        self.checkApiReturn(self.SubscribeMarketData(codes))
        self.waitCompletion("订阅行情")

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
        self._receiver({"code": field.InstrumentID, "price": FILTER(field.LastPrice),
                "open": FILTER(field.OpenPrice), "close": FILTER(field.ClosePrice),
                "highest": FILTER(field.HighestPrice), "lowest": FILTER(field.LowestPrice),
                "upper_limit": FILTER(field.UpperLimitPrice),
                "lower_limit": FILTER(field.LowerLimitPrice),
                "settlement": FILTER(field.SettlementPrice), "volume": field.Volume,
                "turnover": field.Turnover, "open_interest": int(field.OpenInterest),
                "pre_close": FILTER(field.PreClosePrice),
                "pre_settlement": FILTER(field.PreSettlementPrice),
                "pre_open_interest": int(field.PreOpenInterest),
                "ask1": (FILTER(field.AskPrice1), field.AskVolume1),
                "bid1": (FILTER(field.BidPrice1), field.BidVolume1),
                "ask2": (FILTER(field.AskPrice2), field.AskVolume2),
                "bid2": (FILTER(field.BidPrice2), field.BidVolume2),
                "ask3": (FILTER(field.AskPrice3), field.AskVolume3),
                "bid3": (FILTER(field.BidPrice3), field.BidVolume3),
                "ask4": (FILTER(field.AskPrice4), field.AskVolume4),
                "bid4": (FILTER(field.BidPrice4), field.BidVolume4),
                "ask5": (FILTER(field.AskPrice5), field.AskVolume5),
                "bid5": (FILTER(field.BidPrice5), field.BidVolume5)})

    def unsubscribe(self, codes):
        self.resetCompletion()
        self.checkApiReturn(self.UnSubscribeMarketData(codes))
        self.waitCompletion("取消订阅行情")

    def OnRspUnSubMarketData(self, field, info, _, is_last):
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        logging.info("已取消订阅<%s>的行情..." % field.InstrumentID)
        if is_last:
            self.notifyCompletion()


class TraderImpl(SpiHelper, CTP.TraderApiPy):

    def __init__(self, front, broker_id, app_id, auth_code, user_id, password):
        SpiHelper.__init__(self)
        CTP.TraderApiPy.__init__(self)
        self._last_query_time = 0
        self._broker_id = broker_id
        self._app_id = app_id
        self._auth_code = auth_code
        self._user_id = user_id
        self._password = password
        self._order_action = None
        self._order_ref = 0
        flow_dir = DATA_DIR + "td_flow/"
        os.makedirs(flow_dir, exist_ok = True)
        self.Create(flow_dir)
        self.RegisterFront(front)
        self.SubscribePrivateTopic(2)   #THOST_TERT_QUICK
        self.SubscribePublicTopic(2)    #THOST_TERT_QUICK
        self.Init()
        self.waitCompletion("登录交易会话")
        del self._app_id, self._auth_code, self._password
        self._getInstruments()
        self._getTransferRegisters()

    def _limitFrequency(self):
        delta = time.time() - self._last_query_time
        if delta < 1:
            time.sleep(1 - delta)
        self._last_query_time = time.time()

    def __del__(self):
        logging.info("已登出交易服务器...")

    def OnFrontConnected(self):
        logging.info("已连接交易服务器...")
        field = CTPStruct.ReqAuthenticateField(BrokerID = self._broker_id,
                AppID = self._app_id, AuthCode = self._auth_code, UserID = self._user_id)
        self.checkApiReturnInCallback(self.ReqAuthenticate(field, 1))

    def OnRspAuthenticate(self, _, info, req_id, is_last):
        assert(req_id == 1)
        assert(is_last)
        if not self.checkRspInfoInCallback(info):
            return
        logging.info("已通过交易终端认证...")
        field = CTPStruct.ReqUserLoginField(BrokerID = self._broker_id,
                UserID = self._user_id, Password = self._password)
        self.checkApiReturnInCallback(self.ReqUserLogin(field, 0))

    def OnRspUserLogin(self, field, info, req_id, is_last):
        assert(req_id == 0)
        assert(is_last)
        if not self.checkRspInfoInCallback(info):
            return
        self._front_id = field.FrontID
        self._session_id = field.SessionID
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

    def _getInstruments(self):
        file_path = DATA_DIR + "instruments.dat"
        now_date = time.strftime("%Y-%m-%d", time.localtime())
        if os.path.exists(file_path):
            fd = open(file_path)
            cached_date = fd.readline()
            if cached_date[: -1] == now_date:
                self._instruments = json.load(fd)
                fd.close()
                logging.info("已加载全部共%d个合约..." % len(self._instruments))
                return
            fd.close()
        self._instruments = {}
        field = CTPStruct.QryInstrumentField()
        self.resetCompletion()
        self._limitFrequency()
        self.checkApiReturn(self.ReqQryInstrument(field, 3))
        last_count = 0
        while True:
            try:
                self.waitCompletion("获取所有合约")
                break
            except TimeoutError as e:
                count = len(self._instruments)
                if count == last_count:
                    raise e
                logging.info("已获取%d个合约..." % count)
                last_count = count
        fd = open(file_path, "w")
        fd.write(now_date + "\n")
        json.dump(self._instruments, fd)
        fd.close()
        logging.info("已保存全部共%d个合约..." % len(self._instruments))

    def OnRspQryInstrument(self, field, info, req_id, is_last):
        assert(req_id == 3)
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        if field:
            if field.OptionsType == '1':        #THOST_FTDC_CP_CallOptions
                option_type = "call"
            elif field.OptionsType == '2':      #THOST_FTDC_CP_PutOptions
                option_type = "put"
            else:
                option_type = None
            expire_date = None if field.ExpireDate == "" else       \
                    time.strftime("%Y-%m-%d", time.strptime(field.ExpireDate, "%Y%m%d"))
            self._instruments[field.InstrumentID] = {"name": field.InstrumentName,
                    "exchange": field.ExchangeID, "multiple": field.VolumeMultiple,
                    "price_tick": field.PriceTick, "expire_date": expire_date,
                    "long_margin_ratio": FILTER(field.LongMarginRatio),
                    "short_margin_ratio": FILTER(field.ShortMarginRatio),
                    "option_type": option_type, "strike_price": FILTER(field.StrikePrice),
                    "is_trading": bool(field.IsTrading)}
        if is_last:
            logging.info("已获取全部共%d个合约..." % len(self._instruments))
            self.notifyCompletion()

    def getInstrument(self, code):
        if code not in self._instruments:
            raise ValueError("合约<%s>不存在" % code)
        return self._instruments[code].copy()

    def _getTransferRegisters(self):
        self._bank_names = {}
        field = CTPStruct.QryContractBankField(BrokerID = self._broker_id)
        self.resetCompletion()
        self._limitFrequency()
        self.checkApiReturn(self.ReqQryContractBank(field, 4))
        self.waitCompletion("获取期货公司支持的银行")
        self._trans_regs = []
        field = CTPStruct.QryAccountregisterField(BrokerID = self._broker_id,
                AccountID = self._user_id)
        self.resetCompletion()
        self._limitFrequency()
        self.checkApiReturn(self.ReqQryAccountregister(field, 5))
        self.waitCompletion("获取银期转账签约关系")
        del self._bank_names

    def OnRspQryContractBank(self, field, info, req_id, is_last):
        assert(req_id == 4)
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        if field:
            self._bank_names[field.BankID] = field.BankName
        if is_last:
            logging.info("已获取期货公司支持的银行...")
            self.notifyCompletion()

    def OnRspQryAccountregister(self, field, info, req_id, is_last):
        assert(req_id == 5)
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        if field and field.OpenOrDestroy == "1":    #THOST_FTDC_OOD_Open = 1
            assert(field.BrokerID == self._broker_id)
            assert(field.AccountID == self._user_id)
            self._trans_regs.append({"bank_name": self._bank_names[field.BankID],
                    "bank_id": field.BankID, "bank_branch_id": field.BankBranchID,
                    "bank_account": field.BankAccount, "currency": field.CurrencyID,
                    "broker_branch_id": field.BrokerBranchID})
        if is_last:
            logging.info("已获取银期转账签约关系...")
            self.notifyCompletion()

    def getAccount(self):
        #THOST_FTDC_BZTP_Future = 1
        field = CTPStruct.QryTradingAccountField(BrokerID = self._broker_id,
                InvestorID = self._user_id, CurrencyID = "CNY", BizType = '1')
        self.resetCompletion()
        self._limitFrequency()
        self.checkApiReturn(self.ReqQryTradingAccount(field, 6))
        self.waitCompletion("获取资金账户")
        return self._account

    def OnRspQryTradingAccount(self, field, info, req_id, is_last):
        assert(req_id == 6)
        assert(is_last)
        if not self.checkRspInfoInCallback(info):
            return
        self._account = {"balance": field.Balance, "margin": field.CurrMargin,
                "available": field.Available, "withdraw": field.WithdrawQuota}
        logging.info("已获取资金账户...")
        self.notifyCompletion()

    def getOrders(self):
        self._orders = {}
        field = CTPStruct.QryOrderField(BrokerID = self._broker_id,
                InvestorID = self._user_id)
        self.resetCompletion()
        self._limitFrequency()
        self.checkApiReturn(self.ReqQryOrder(field, 7))
        self.waitCompletion("获取所有报单")
        return self._orders

    def _gotOrder(self, order):
        if len(order.OrderSysID) == 0:
            return
        oid = "%s@%s" % (order.OrderSysID, order.InstrumentID)
        (direction, volume) = (int(order.Direction), order.VolumeTotalOriginal)
        assert(direction in (0, 1))
        if order.CombOffsetFlag == '1':     #THOST_FTDC_OFEN_Close
            direction = 1 - direction
            volume = -volume
        direction = "short" if direction else "long"
        #THOST_FTDC_OST_AllTraded = 0, THOST_FTDC_OST_Canceled = 5
        is_active = order.OrderStatus not in ('0', '5')
        assert(oid not in self._orders)
        self._orders[oid] = {"code": order.InstrumentID, "direction": direction,
                "price": order.LimitPrice, "volume": volume,
                "volume_traded": order.VolumeTraded, "is_active": is_active}

    def OnRspQryOrder(self, field, info, req_id, is_last):
        assert(req_id == 7)
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        if field:
            self._gotOrder(field)
        if is_last:
            logging.info("已获取所有报单...")
            self.notifyCompletion()

    def getPositions(self):
        self._positions = []
        field = CTPStruct.QryInvestorPositionField(BrokerID = self._broker_id,
                InvestorID = self._user_id)
        self.resetCompletion()
        self._limitFrequency()
        self.checkApiReturn(self.ReqQryInvestorPosition(field, 8))
        self.waitCompletion("获取所有持仓")
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
        assert(req_id == 8)
        if not self.checkRspInfoInCallback(info):
            assert(is_last)
            return
        if field:
            self._gotPosition(field)
        if is_last:
            logging.info("已获取所有持仓...")
            self.notifyCompletion()

    def OnRtnOrder(self, order):
        if self._order_action:
            if self._order_action(order):
                self._order_action = None

    def _handleNewOrder(self, order):
        order_ref = None if len(order.OrderRef) == 0 else int(order.OrderRef)
        if (order.FrontID, order.SessionID, order_ref) !=               \
                (self._front_id, self._session_id, self._order_ref):
            return False
        logging.debug(order)
        if order.OrderStatus == 'a':                #THOST_FTDC_OST_Unknown
            return False
        if order.OrderSubmitStatus == '4':          #THOST_FTDC_OSS_InsertRejected
            self.notifyCompletion(order.StatusMsg)
            return True
        if order.TimeCondition == '1':              #THOST_FTDC_TC_IOC
            #THOST_FTDC_OST_AllTraded = 0, THOST_FTDC_OST_Canceled = 5
            if order.OrderStatus in ('0', '5'):
                logging.info("已执行IOC单，成交量：%d" % order.VolumeTraded)
                self._traded_volume = order.VolumeTraded
                self.notifyCompletion()
                return True
        else:
            assert(order.TimeCondition == '3')      #THOST_FTDC_TC_GFD
            if order.OrderSubmitStatus == '3':      #THOST_FTDC_OSS_Accepted
                #THOST_FTDC_OST_AllTraded = 0, THOST_FTDC_OST_PartTradedQueueing = 1
                #THOST_FTDC_OST_PartTradedNotQueueing = 2, THOST_FTDC_OST_NoTradeQueueing = 3
                #THOST_FTDC_OST_NoTradeNotQueueing = 4, THOST_FTDC_OST_Canceled = 5
                assert(order.OrderStatus in ('0', '1', '2', '3', '4', '5'))
                assert(len(order.OrderSysID) != 0)
                self._order_id = "%s@%s" % (order.OrderSysID, order.InstrumentID)
                logging.info("已提交限价单（单号：<%s>）" % self._order_id)
                self.notifyCompletion()
                return True
        return False

    def _order(self, code, direction, volume, price, min_volume):
        if code not in self._instruments:
            raise ValueError("合约<%s>不存在！" % code)
        exchange = self._instruments[code]["exchange"]
        if direction == "long":
            direction = 0               #THOST_FTDC_D_Buy
        elif direction == "short":
            direction = 1               #THOST_FTDC_D_Sell
        else:
            raise ValueError("错误的买卖方向<%s>" % direction)
        if volume != int(volume) or volume == 0:
            raise ValueError("交易数量<%s>必须是非零整数" % volume)
        if volume > 0:
            offset_flag = '0'           #THOST_FTDC_OF_Open
        else:
            offset_flag = '1'           #THOST_FTDC_OF_Close
            volume = -volume
            direction = 1 - direction
        direction = str(direction)
        #Market Price Order
        if price == 0:
            if exchange == "CFFEX":
                price_type = 'G'        #THOST_FTDC_OPT_FiveLevelPrice
            else:
                price_type = '1'        #THOST_FTDC_OPT_AnyPrice
            #THOST_FTDC_TC_IOC, THOST_FTDC_VC_AV
            (time_cond, volume_cond) = ('1', '1')
        #Limit Price Order
        elif min_volume == 0:
            #THOST_FTDC_OPT_LimitPrice, THOST_FTDC_TC_GFD, THOST_FTDC_VC_AV
            (price_type, time_cond, volume_cond) = ('2', '3', '1')
        #FAK Order
        else:
            min_volume = abs(min_volume)
            if min_volume > volume:
                raise ValueError("最小成交量<%s>不能超过交易数量<%s>" % (min_volume, volume))
            #THOST_FTDC_OPT_LimitPrice, THOST_FTDC_TC_IOC, THOST_FTDC_VC_MV
            (price_type, time_cond, volume_cond) = ('2', '1', '2')
        self._order_ref += 1
        self._order_action = self._handleNewOrder
        field = CTPStruct.InputOrderField(BrokerID = self._broker_id,
                InvestorID = self._user_id, ExchangeID = exchange, InstrumentID = code,
                Direction = direction, CombOffsetFlag = offset_flag,
                TimeCondition = time_cond, VolumeCondition = volume_cond,
                OrderPriceType = price_type, LimitPrice = price,
                VolumeTotalOriginal = volume, MinVolume = min_volume,
                CombHedgeFlag = '1',            #THOST_FTDC_HF_Speculation
                ContingentCondition = '1',      #THOST_FTDC_CC_Immediately
                ForceCloseReason = '0',         #THOST_FTDC_FCC_NotForceClose
                OrderRef = "%12d" % self._order_ref)
        self.resetCompletion()
        self.checkApiReturn(self.ReqOrderInsert(field, 9))
        self.waitCompletion("录入报单")

    def OnRspOrderInsert(self, field, info, req_id, is_last):
        assert(req_id == 9)
        assert(is_last)
        self.OnErrRtnOrderInsert(field, info)

    def OnErrRtnOrderInsert(self, _, info):
        success = self.checkRspInfoInCallback(info)
        assert(not success)

    def orderMarket(self, code, direction, volume):
        self._order(code, direction, volume, 0, 0)
        return self._traded_volume

    def orderFAK(self, code, direction, volume, price, min_volume):
        assert(price > 0)
        self._order(code, direction, volume, price, 1 if min_volume == 0 else min_volume)
        return self._traded_volume

    def orderFOK(self, code, direction, volume, price):
        return self.orderFAK(code, direction, volume, price, volume)

    def orderLimit(self, code, direction, volume, price):
        assert(price > 0)
        self._order(code, direction, volume, price, 0)
        return self._order_id

    def _handleDeleteOrder(self, order):
        oid = "%s@%s" % (order.OrderSysID, order.InstrumentID)
        if oid != self._order_id:
            return False
        logging.debug(order)
        if order.OrderSubmitStatus == '5':      #THOST_FTDC_OSS_CancelRejected
            self.notifyCompletion(order.StatusMsg)
            return True
        #THOST_FTDC_OST_AllTraded = 0, THOST_FTDC_OST_Canceled = 5
        if order.OrderStatus in ('0', '5'):
            logging.info("已撤销限价单，单号：<%s>" % self._order_id)
            self.notifyCompletion()
            return True
        return False

    def deleteOrder(self, order_id):
        items = order_id.split("@")
        if len(items) != 2:
            raise ValueError("订单号<%s>格式错误" % order_id)
        (sys_id, code) = items
        if code not in self._instruments:
            raise ValueError("订单号<%s>中的合约号<%s>不存在" % (order_id, code))
        field = CTPStruct.InputOrderActionField(BrokerID = self._broker_id,
                InvestorID = self._user_id, UserID = self._user_id,
                ActionFlag = '0',               #THOST_FTDC_AF_Delete
                ExchangeID = self._instruments[code]["exchange"],
                InstrumentID = code, OrderSysID = sys_id)
        self.resetCompletion()
        self._order_id = order_id
        self._order_action = self._handleDeleteOrder
        self.checkApiReturn(self.ReqOrderAction(field, 10))
        self.waitCompletion("撤销报单")

    def OnRspOrderAction(self, field, info, req_id, is_last):
        assert(req_id == 10)
        assert(is_last)
        self.OnErrRtnOrderAction(field, info)

    def OnErrRtnOrderAction(self, _, info):
        success = self.checkRspInfoInCallback(info)
        assert(not success)

    def transfer(self, money, password, bank_name = None, bank_account = None):
        if money == 0:
            return
        found = False
        if bank_account:
            for reg in self._trans_regs:
                if reg["bank_account"] == bank_account:
                    if bank_name and reg["bank_name"] != bank_name:
                        raise ValueError("银行账号<%s>属于<%s>，而不是<%s>" %
                                (bank_account, reg["bank_name"], bank_name))
                    found = True
                    break
            if not found:
                raise ValueError("找不到银行账号<%s>的银期签约关系" % bank_account)
        elif bank_name:
            for reg in self._trans_regs:
                if reg["bank_name"] == bank_name:
                    found = True
                    break
            if not found:
                raise ValueError("找不到与<%s>的银期签约关系" % bank_name)
        else:
            raise ValueError("参数<bank_name>和<bank_account>至少填写一个")
        field = CTPStruct.ReqTransferField(AccountID = self._user_id,
                BrokerID = self._broker_id, BrokerBranchID = reg["broker_branch_id"],
                BankID = reg["bank_id"], BankBranchID = reg["bank_branch_id"],
                BankAccount = reg["bank_account"], Password = password,
                CurrencyID = reg["currency"], TradeAmount = abs(money),
                VerifyCertNoFlag = "1",             #THOST_FTDC_YNI_No
                CustType = "\0", IdCardType = "\0",
                BankAccType = "\0", BankSecuAccType = "\0", FeePayFlag = "\0",
                SecuPwdFlag = "\0", BankPwdFlag = "\0",
                TransferStatus = "\0", LastFragment = "\0")
        self.resetCompletion()
        if money > 0:
            self.ReqFromBankToFutureByFuture(field, 11)
            self.waitCompletion("银期转账（银行->期货）")
        else:
            self.ReqFromFutureToBankByFuture(field, 12)
            self.waitCompletion("银期转账（期货->银行）")

    def OnRspFromBankToFutureByFuture(self, _, info, req_id, is_last):
        assert(req_id == 11)
        assert(is_last)
        success = self.checkRspInfoInCallback(info)
        assert(not success)

    def OnRtnFromBankToFutureByFuture(self, field):
        logging.debug(field)
        if field.ErrorID == 0:
            logging.info("已完成银期转账（银行->期货）")
            self.notifyCompletion()
        else:
            self.notifyCompletion(field.ErrorMsg)

    def OnRspFromFutureToBankByFuture(self, _, info, req_id, is_last):
        assert(req_id == 12)
        assert(is_last)
        success = self.checkRspInfoInCallback(info)
        assert(not success)

    def OnRtnFromFutureToBankByFuture(self, field):
        logging.debug(field)
        if field.ErrorID == 0:
            logging.info("已完成银期转账（期货->银行）")
            self.notifyCompletion()
        else:
            self.notifyCompletion(field.ErrorMsg)


class Client:

    def __init__(self, md_front, td_front, broker_id, app_id, auth_code, user_id, password):
        self._md = QuoteImpl(md_front)
        self._td = TraderImpl(td_front, broker_id, app_id, auth_code, user_id, password)

    def setReceiver(self, func):
        return self._md.setReceiver(func)

    def subscribe(self, codes):
        for code in codes:
            if code not in self._td._instruments:
                raise ValueError("合约<%s>不存在" % code)
        self._md.subscribe(codes)

    def unsubscribe(self, codes):
        self._md.unsubscribe(codes)

    def getInstrument(self, code):
        return self._td.getInstrument(code)

    def getAccount(self):
        return self._td.getAccount()

    def getOrders(self):
        return self._td.getOrders()

    def getPositions(self):
        return self._td.getPositions()

    def orderMarket(self, code, direction, volume):
        return self._td.orderMarket(code, direction, volume)

    def orderFAK(self, code, direction, volume, price, min_volume):
        return self._td.orderFAK(code, direction, volume, price, min_volume)

    def orderFOK(self, code, direction, volume, price):
        return self._td.orderFOK(code, direction, volume, price)

    def orderLimit(self, code, direction, volume, price):
        return self._td.orderLimit(code, direction, volume, price)

    def deleteOrder(self, order_id):
        self._td.deleteOrder(order_id)

    def transferFromBank(self, money, password, bank_name = None, bank_account = None):
        self._td.transfer(abs(money), password, bank_name, bank_account)

    def transferToBank(self, money, password, bank_name = None, bank_account = None):
        self._td.transfer(-abs(money), password, bank_name, bank_account)
