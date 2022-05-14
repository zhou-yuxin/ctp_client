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
安装过程中可能会报错，比较典型的是缺少Microsoft Visual C++ 14.0 Build Tools。这个自己网上下载，推荐这篇《[Microsoft Visual C++ 14.0 is required解决方法](https://zhuanlan.zhihu.com/p/126669852)》]

## 接口