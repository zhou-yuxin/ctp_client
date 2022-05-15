# ctp_client

基于ctpwrapper的客户端接口，做国内期货和期权量化交易的神器。

## 准备工作：

安装cython，因为官方CTP接口都是C++写的，使用cython跟Python对接。
```
pip install cython --upgrade
```
然后安装ctpwrapper，一般使用如下命令：
```
pip install ctpwrapper --upgrade
```
之所以说“一般”，是因为有些期货公司的CTP系统版本不一定是最新的。比如说今天（2022年5月14日），CTP最新版本是v6.6.5，而我用的华泰期货要求的CTP版本是v6.6.1，如果直接使用上述命令安装了最新版，是连不上华泰期货的。以v6.6.1为例，安装指定版本的ctpwrapper：
```
pip install ctpwrapper==6.6.1
```
安装过程中可能会报错，比较典型的是缺少Microsoft Visual C++ 14.0 Build Tools。这个自己网上下载，推荐这篇《[Microsoft Visual C++ 14.0 is required解决方法](https://zhuanlan.zhihu.com/p/126669852)》。

## 接口

所有对外接口都可以查看client.py中的Client类。

### >>> 构造函数：
```
def __init__(self, md_front, td_front, md_flow_dir, td_flow_dir,
            broker_id, app_id, auth_code, user_id, password)
```
md_front和td_front分别是服务器地址，比如上期技术提供的仿真平台Simnow（全天候版）地址是"tcp://180.168.146.187:10131"和
"tcp://180.168.146.187:10130"。md_flow_dir和td_flow_dir是行情数据流与交易数据流存放的本地目录，必须事先创建好，而且必须以'/'结尾。比如创建了/home/yuxin/my_dir，那么字符串必须设为"/home/yuxin/my_dir/"。broker_id是每个期货公司自定义的，需要向其索取。app_id和auth_code是向期货公司申请开通CTP权限（看穿式监管）时设定的。user_id和password就是期货账户和密码。

### >>> 订阅/取消订阅
```
def subscribe(self, codes)
def unsubscribe(self, codes)
```
这两个接口接收数组codes，其每一个元素是一个字符串，即合约代码。

### >>> 设置行情接收器
```
def setReceiver(self, func)
```
func是一个可调用体（比如函数或者实现了__call__()接口的对象），能接收一个参数。设置行情接收器后，当服务器有新的行情推送时，func就会被调用，参数为一个dict，为一条新的行情数据，包含如下字段：
|  字段               |  类型           |  含义                   |
| :------------------ | :------------- | :-----------------------|
|  code               |  str           |  合约代码                |
|  price              |  float         |  最新价                  |
|  open               |  float         |  开盘价                  |
|  close              |  float         |  收盘价                  |
|  highest            |  float         |  最高价                  |
|  lowest             |  float         |  最低价                  |
|  upper_limit        |  float         |  涨停价                  |
|  lower_limit        |  float         |  跌停价                  |
|  settlement         |  float         |  结算价                  |
|  volume             |  int           |  成交量                  |
|  turnover           |  float         |  成交额                  |
|  open_interest      |  int           |  持仓量                  |
|  pre_close          |  float         |  昨日收盘价              |
|  pre_settlement     |  float         |  昨日结算价              |
|  pre_open_interest  |  int           |  昨日持仓量              |
|  ask1               |  (float, int)  |  第一档卖盘（价格x数量）  |
|  bid1               |  (float, int)  |  第一档买盘（价格x数量）  |
|  ask2               |  (float, int)  |  第二档卖盘（价格x数量）  |
|  bid2               |  (float, int)  |  第二档买盘（价格x数量）  |
|  ask3               |  (float, int)  |  第三档卖盘（价格x数量）  |
|  bid3               |  (float, int)  |  第三档买盘（价格x数量）  |
|  ask4               |  (float, int)  |  第四档卖盘（价格x数量）  |
|  bid4               |  (float, int)  |  第四档买盘（价格x数量）  |
|  ask5               |  (float, int)  |  第五档卖盘（价格x数量）  |
|  bid5               |  (float, int)  |  第五档买盘（价格x数量）  |

注意，有些字段可能为None，表示当前没有值。比如收盘前close、settlement就是None。另外，通常期货只有第一档摆盘有数据，因此ask2、bid2等其他档的价格也为None。

### >>> 查询持仓
```
def getPositions(self)
```
返回一个list，每个元素是一个dict，包含如下字段：
|  字段       |  类型                       |  含义                              |
| :---------- | :------------------------- | :----------------------------------|
|  code       |  str                       |  合约代码                          |
|  direction  |  str in ("long", "short")  |  方向（多头或空头）                 |
|  volume     |  int                       |  数量                              |
|  margin     |  float                     |  占用保证金                         |
|  cost       |  float                     |  持仓成本（=开仓均价x数量x合约乘数）  |

### >>> 查询订单
```
def getOrders(self)
```
返回一个dict，键为订单号，值是一个dict，表示一笔订单，包含如下字段：
|  字段           |  类型                       |  含义                   |
| :-------------- | :------------------------- | :-----------------------|
|  code           |  str                       |  合约代码                |
|  direction      |  str in ("long", "short")  |  方向（多头或空头）       |
|  price          |  float                     |  价格                    |
|  volume         |  int                       |  数量                    |
|  volume_traded  |  int                       |  已成交数量              |
|  is_active      |  bool                      |  是否活跃                |

is_active若为False，则表示该订单已经不再有效，不会再有新的成交，通常情况为全部成交、已撤单或者废单。需要注意dict的键（订单号），虽然是一个内容为整数的字符串，而且通常开头有若干个空格，但不要随意截断，CTP系统只认特定长度的字符串表示的订单号。

### >>> 提交限价单
```
def orderLimit(self, code, direction, volume, price)
```
code为合约代码，direction为字符串"long"或者"short"之一，表示多头或空头。volume为正整数，表示数量。price为float类型的价格。提交成功返回订单号。

### >>> 撤单
```
def deleteOrder(self, order_id)
```
已提交未完全成交的限价单可以撤单。order_id为orderLimit()返回的订单号。

### >>> 提交FAK单
```
def orderFAK(self, code, direction, volume, price, min_volume)
```
FAK（Fill and Kill）是一种特殊的报单类型，该报单被交易所接收后，交易所会扫描市场行情，在当时的行情下如果能成交至少min_volume手则成交（最多成交volume手），剩余未成交的则立即撤销。由于FAK的执行后订单一定是inactive状态，无需撤单，因此也没有返回订单号的必要，而是返回成交数量。从FAK定义可知，返回值要么是0，要么介于[min_volume, volume]之间。

### >>> 提交FOK单
```
def orderFOK(self, code, direction, volume, price)
```
FOK（Fill or Kill）是一种特殊的报单类型，该报单被交易所接收后，交易所会扫描市场行情，如果在当时的市场行情下该报单可以立即全部成交，否则立即全部撤销。可以把FOK看作min_volume = volume的FAK。
