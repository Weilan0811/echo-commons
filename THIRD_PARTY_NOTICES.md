# 第三方组件与素材说明

项目自行开发的代码采用 [MIT 许可证](LICENSE)。下列第三方字体、程序与规则资料保留各自的名称、来源和许可；根许可证不替代这些条款。

## 随仓库提供的字体

| 字体 | 本地位置 | 来源与许可 |
| --- | --- | --- |
| Inter | `frontend/public/fonts/Inter-*.woff2` | [Inter 项目](https://github.com/rsms/inter)，SIL Open Font License 1.1；保留[版权及许可原文](frontend/public/fonts/LICENSE.txt) |
| Noto Sans SC | `frontend/public/fonts/noto-sans-sc-*.woff2` | [Google Fonts](https://github.com/google/fonts/tree/main/ofl/notosanssc)，SIL Open Font License 1.1；保留[版权及许可原文](frontend/public/fonts/OFL.txt) |

## 可选五子棋分析程序 Rapfi

安装工具从 [Rapfi 250615 发布版本](https://github.com/dotb1ue/rapfi/tree/250615) 下载程序与配套资源，并保存上游 `Copying.txt` 和 `AUTHORS`。上游许可见[原文](https://github.com/dotb1ue/rapfi/blob/250615/Copying.txt)。

仓库提供宿主适配代码与下载配置，不随 Git 分发引擎二进制和模型权重。下载后的资源保存在被忽略的运行目录，使用和再次分发时需保留对应上游条款。

## 游戏名称与规则资料

- 飞行棋玩法来源及项目决定见[飞行棋规则](docs/gameplay/飞行棋基础规则.md)。
- Kingdomino 名称及规则来源见[玩法规则](docs/gameplay/Kingdomino基础规则.md)，参考 Blue Orange 官方基础规则书。仓库没有附带该规则书 PDF。项目中的玩法实现、地形图形与界面资源不表示与出版商存在关联或获得其背书。

## 项目展示素材

项目人物、封面、背景、装饰、品牌及游戏展示图形使用 AI 生成素材，人物设定由项目作者撰写。README 使用实际界面截图与技术流程图。项目所有者已确认这些内容可以随仓库公开；第三方字体、程序和规则资料的来源及许可分别保留。

## 安装依赖

uv 与 npm 依赖由清单和锁定文件记录，按各依赖许可证使用。依赖目录、本地数据、模型权重、实验记录及个人密钥不随仓库分发。
