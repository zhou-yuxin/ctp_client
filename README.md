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

1. 构造函数：
```
def __init__(self, md_front, td_front, md_flow_dir, td_flow_dir,
            broker_id, app_id, auth_code, user_id, password)
```
md_front和td_front分别是服务器地址，比如上期技术提供的仿真平台Simnow（全天候版）地址是*tcp://180.168.146.187:10131*和
*tcp://180.168.146.187:10130*。md_flow_dir和td_flow_dir是行情数据流与交易数据流存放的本地目录，必须事先创建好，而且必须以'/'结尾。比如创建了*/home/yuxin/my_dir*，那么字符串必须设为*/home/yuxin/my_dir/*。broker_id是每个期货公司自定义的，需要向其索取。app_id和auth_code是向期货公司申请开通CTP权限（看穿式监管）时设定的。user_id和password就是期货账户和密码。