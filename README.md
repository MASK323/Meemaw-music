# Meemaw Music

Meemaw Music 是一款基于 PySide6 开发的 Windows 桌面音乐播放器，界面整体参考网易云音乐客户端与黑胶唱片播放器的设计风格，支持榜单、歌单、歌词、评论、喜欢同步，并通过酷狗概念版账号扫码登录后同步会员信息、匹配网络音源进行播放。

本仓库为 Meemaw Music 的开源学习版本，仅供学习和个人使用。开源版本不包含签到领取会员、自动打卡、批量下载等自动化功能，也不会保存任何账号密码。

> 本项目不是网易云音乐、酷狗音乐或任何音乐平台的官方客户端，与相关平台之间不存在任何关联、授权、赞助或认可关系。

## 开源声明

- 本仓库为 Meemaw Music 的开源版本，源码以学习、研究和交流为目的开放。
- 开源版本不包含任何自动签到、自动领取会员、批量下载、付费内容解锁或绕过数字版权保护（DRM）的逻辑。
- 项目中的代码与视觉实现均为本项目独立完成，仅借鉴通用的交互形态与布局风格。
- 本项目仅用于学习交流，请勿用于商业用途或任何可能侵犯他人合法权益的场景。
- 本项目不会缓存保存任何音乐文件，在退出播放器之后所有临时缓存文件都会删除，保证合法的版权。

### 自定义音源

- 默认音源为酷狗概念版，保持原有逻辑不做任何更改
- 可在设置中自定义补充其他音源，多音源之间支持切换与兜底匹配
- 网络音源匹配带缓存机制，避免重复刷新
- 音源设备信息（kugou_dev.json）随应用自动生成，无需手动配置

### 歌单导入

- 设置中新增歌单导入选项，支持 QQ 音乐、网易云音乐、Apple Music 歌单链接导入
- 导入后自动解析歌单曲目并加入播放列表

### 数据同步

- 榜单数据来自网易云音乐公开接口，主页面与榜单详情页均可展示歌曲
- 精选歌单、热门分类与搜索由网易云音乐接口提供
- 歌曲评论与喜欢数量同步网易云音乐数据，评论支持继续下拉加载更多
- 歌词支持滚动、时间轴显示与点击跳转到对应片段

### 播放能力

- 通过酷狗概念版账号扫码登录后匹配网络音源进行播放
- 支持音质选择，网络音源匹配带缓存机制，避免重复刷新
- 进度条支持拖动与点击跳转，音量支持竖向调节并记忆上次音量
- 顺序播放、列表循环、单曲循环、随机播放四种模式
- 黑胶唱片旋转、唱针拨动动画，播放/暂停状态平滑衔接
- 上拉/下拉播放器动画流畅不卡顿，歌词平滑滚动无抖动

### 系统集成

- 系统托盘与托盘播放器，退出播放器后音乐继续播放
- 最小化、窗口化、全屏模式
- 单实例运行，同一时间只允许开启一个应用
- Windows 任务栏名称默认为 Meemaw Music，播放时显示当前歌曲名称

## 界面截图

<img width="1247" height="898" alt="image" src="https://github.com/user-attachments/assets/bd5d8f82-4551-430d-ac40-b80c05843c21" />

<img width="1920" height="1200" alt="image" src="https://github.com/user-attachments/assets/efe264d4-fb83-40ee-a78d-9f45e057d7b7" />

<img width="1920" height="1200" alt="image" src="https://github.com/user-attachments/assets/5ffc0fce-ebb7-4a4f-978a-fdce16d3abe5" />

<img width="1920" height="1200" alt="image" src="https://github.com/user-attachments/assets/355f8845-4ccb-496e-898b-2eb233c3af36" />

<img width="1920" height="1200" alt="image" src="https://github.com/user-attachments/assets/44eb0888-f6c4-420e-a99c-416b5821f8cd" />

<img width="1920" height="1200" alt="image" src="https://github.com/user-attachments/assets/aab48c94-2a36-41f0-8735-4b15eec4b10e" />

## 登录与会员

### 酷狗概念版扫码登录

- 在软件登录页选择“酷狗概念版扫码”方式
- 使用酷狗概念版 App 扫码完成登录
- 登录后同步酷狗概念版会员信息与剩余天数
- 本程序不会保存任何密码，也不包含签到领取会员功能

### 会员获取提示

以下信息仅为使用提示，与本项目无关，请自行判断其有效性并遵守相关平台规则：

- iOS 系统在爱思助手中下载 3.2.0 版本的酷狗概念版
- 安卓系统可在豌豆荚下载：[https://m.wandoujia.com/apps/8074843/history_v10661](https://m.wandoujia.com/apps/8074843/history_v10661)

通过下方链接可以领取 6 个月会员：

- [https://t1.kugou.com/3XZpN9cG4V2](https://t1.kugou.com/3XZpN9cG4V2)
- [https://activity.kugou.com/lists/v-ec9b6530/shareAndCode2.html](https://activity.kugou.com/lists/v-ec9b6530/shareAndCode2.html)

3.2.0 版本带有听歌签到领取会员功能，没有广告，也没有额外签到任务。

## 快速开始

```bash
git clone https://github.com/MASK323/Meemaw-music.git
cd Meemaw-music
pip install -r requirements.txt
python main.py
```

### 运行环境

- Windows 10/11
- Python 3.10+
- 依赖：PySide6、PyInstaller、mutagen

### 打包 exe

```bash
pyinstaller "Meemaw music.spec"
```

构建产物位于 `dist/Meemaw music/`。

## 项目结构

- `main.py`：程序入口
- `app/`：核心代码、界面资源与动画
  - `app/core/`：播放、音源匹配、自定义音源管理、歌单导入、主题管理等
  - `app/ui/`：主窗口、页面、控件与主题（原版模块保留为 `_xxx_original`，补丁模块在源码中直接生效）
- `api/app_win.exe`：网络音源匹配辅助进程
- `Meemaw music.spec`：PyInstaller 打包配置
- `requirements.txt`：Python 依赖列表

## 技术栈

- PySide6：桌面界面与窗口动画
- QSS 与自定义动画：网易云风格视觉、黑胶唱片与唱针动效
- 网易云音乐接口：榜单、歌单、搜索、评论、喜欢数量
- 酷狗概念版登录：账号扫码、会员信息同步与网络音源匹配
- 自定义音源与多平台歌单导入：QQ 音乐、网易云音乐、Apple Music

## 数据与版权声明

- 本项目不内置、不随安装包分发任何歌曲文件、专辑封面、歌词文本、艺人照片等受版权保护的素材。
- 榜单、歌单、歌曲元数据、歌词与评论等信息通过第三方公开接口获取，仅用于个人学习场景下的界面展示，程序不将这些内容持久化存储或再次分发。
- 本项目不提供歌曲下载、转存、离线缓存、批量抓取、付费内容解锁或绕过数字版权保护（DRM）的功能。
- 所有展示内容的知识产权归原作者或相应版权方所有；请遵守你所在地区的法律法规以及相关平台的服务条款。
- 本项目与网易云音乐、酷狗音乐等平台之间不存在任何关联、授权、赞助或认可关系，任何商标、名称与产品标识均归其各自所有者所有。
- 若权利人认为本项目涉及侵权内容，请联系项目维护者，我们会在确认后及时处理。

## 免责声明

- 本开源版本仅供学习与交流，不保证功能完整、持续更新或长期可用。
- 请遵守酷狗音乐、网易云音乐及相关服务条款，自行承担使用本软件的一切风险与责任。
- 因网络接口调整、账号状态变化或第三方服务变更导致的任何问题，均与本项目无关。
- 本 README 中出现的第三方链接与下载渠道仅为信息提示，其内容与安全性与本项目无关。

## 开发者

- 开发者：MASK323
- GitHub 主页：https://github.com/MASK323
- 项目地址：https://github.com/MASK323/Meemaw-music

## 借鉴与致谢

- 界面布局、色彩与播放器交互参考网易云音乐客户端
- 项目在界面与交互设计上参考并借鉴了 [MoeKoeMusic](https://github.com/MoeKoeMusic/MoeKoeMusic)
- 感谢所有开源社区与开源项目带来的学习支持
