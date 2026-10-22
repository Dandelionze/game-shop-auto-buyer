# GitHub 开源上传操作指引

## 第一步：准备仓库

1. 登录 GitHub，点击右上角「+」→「New repository」
2. 仓库名称：`game-shop-auto-buyer`（或其他你喜欢的名字）
3. 描述：`游戏店铺自动批量购买工具`
4. 选择 Public（公开）
5. 不要勾选「Add a README file」（我们本地已有）
6. 点击「Create repository」

## 第二步：初始化本地 Git

打开 PowerShell，进入项目目录：

```powershell
cd C:\Users\chenz\Doubao\chats\2026-10-22\new-chat
git init
git add .
git commit -m "首次提交：游戏店铺自动批量购买工具"
```

## 第三步：关联远程仓库并推送

```powershell
git branch -M main
git remote add origin https://github.com/你的用户名/game-shop-auto-buyer.git
git push -u origin main
```

## 第四步：验证隐私

上传前检查以下文件是否包含隐私信息：

- [ ] `shop_buyer.py` - 无游戏特定坐标
- [ ] `shop_presets.json` - 全是 0 占位符
- [ ] `README.md` - 无个人信息
- [ ] `使用说明.md` - 无游戏特定名称
- [ ] `.gitignore` - 已排除配置文件

## 第五步：完善 GitHub 仓库

1. 进入仓库页面，点击「About」→ 齿轮图标
2. 添加 Topics：`python`、`automation`、`tkinter`、`game-tool`
3. 点击「Releases」→「Create a new release」发布第一个版本

## 文件清单（最终上传）

| 文件 | 说明 |
|------|------|
| `shop_buyer.py` | 主程序 |
| `start.bat` | 启动脚本 |
| `start.vbs` | 静默启动脚本 |
| `shop_presets.json` | 预设配置模板（全0占位） |
| `README.md` | GitHub 首页说明 |
| `使用说明.md` | 详细使用文档 |
| `.gitignore` | Git 忽略规则 |
| `GitHub上传指引.md` | 本文件 |

## 隐私检查清单

- [x] 无游戏名称（鸣潮、Wuthering Waves 等）
- [x] 无个人坐标数据
- [x] 无个人信息
- [x] 配置文件全是占位符
- [x] .gitignore 排除了本地配置
