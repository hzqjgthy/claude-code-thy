# FPS Web Prototype

## 新手先看

- `docs/PROJECT_ONBOARDING.md`：给只懂 Python 的新手准备的详细项目导读
- `docs/TUNING_GUIDE.md`：当前项目参数调节说明

这份 `README.md` 是项目的常驻启动、试玩、验证说明。
后续每次新增功能，都应该优先同步这里，让你始终可以按这一份文档把项目跑起来。

## 当前项目配置结构

当前项目建议你先记住这 7 个核心入口：

- `src/game/config/systemTuning.ts`
  系统级参数。负责全局手感，例如移动、镜头、跳跃、音频节奏、子弹印记上限。
- `src/game/content/gameSelection.ts`
  默认内容选择。负责“启动游戏时”默认用哪张图、哪把武器、启用哪些敌人。
- `src/game/content/weapons/weaponCatalog.ts`
  武器注册表。负责定义项目里有哪些武器，以及每把武器的伤害、音效、印记和视图模型。
- `src/game/content/enemies/enemyCatalog.ts`
  敌人内容注册表。这里只放敌人的纯数值配置，例如生命、攻击、移动、碰撞和整体大小倍率。
- `src/game/content/levels/levelCatalog.ts`
  关卡注册表。负责定义项目里有哪些关卡，以及每张关卡的名字、介绍文案和创建入口。
- `src/game/enemies/EnemyRuntimeCatalog.ts`
  敌人运行时装配入口。负责把敌人配置接到具体模型、动画、受击反馈和爆头命中体。
- `src/game/content/ui/gameHelpContent.ts`
  游戏帮助内容。负责暂停菜单里的帮助页文案和键位说明。

可以用一句话理解：

- `systemTuning.ts`：调全局手感
- `gameSelection.ts`：设默认开局内容
- `weaponCatalog.ts`：列出所有武器
- `enemyCatalog.ts`：列出所有敌人数值
- `levelCatalog.ts`：列出所有关卡
- `EnemyRuntimeCatalog.ts`：把敌人数值接到实际模型和动画

它们之间当前的调用关系是：

1. `src/main.ts` 启动整个应用，创建 `GameDirector`。
2. `GameDirector.ts` 从 `gameSelection.ts` 读取默认开局配置。
3. `GameDirector.ts` 创建当前这一局的 `GameApp.ts`，并管理暂停、重开、选关。
4. `GameApp.ts` 再根据当前 `level id` 和 `weapon id` 去 `levelCatalog.ts`、`weaponCatalog.ts` 取出真正要用的定义。
5. `EnemyManager.ts` 根据当前启用敌人列表，先读取 `enemyCatalog.ts` 的纯配置，再通过 `EnemyRuntimeCatalog.ts` 装配成可刷新的敌人原型。

当前地图系统已经整理成“共享工具 + 关卡文件夹”结构，主要看这些文件：

- `src/game/world/shared/desertWorldKit.ts`：沙漠风格关卡共享搭建工具
- `src/game/world/levels/dust2_classic/index.ts`：第一关 Dust2 风格关卡总入口
- `src/game/world/levels/dust2_classic/layout.ts`：第一关地图布局、灯光和碰撞
- `src/game/world/levels/dust2_classic/worldData.ts`：第一关出生点与敌人刷新点
- `src/game/world/levels/desert_fortress/index.ts`：第二关 Desert Fortress 总入口
- `src/game/world/levels/desert_fortress/layout.ts`：第二关更复杂的地图布局、灯光和碰撞
- `src/game/world/levels/desert_fortress/worldData.ts`：第二关出生点与敌人刷新点

## 当前版本能玩什么

当前版本已经包含：

- Web 版第一人称视角
- 默认开局进入第一关，并停在暂停界面
- 暂停界面支持“进入战场 / 继续游戏 / 重启本关卡 / 选择关卡 / 游戏帮助”
- 两张可切换关卡：`dust2_classic` 与 `desert_fortress`
- 第二关 `desert_fortress` 的多路线堡垒地图
- WASD 移动和鼠标观察
- Shift 冲刺
- Space 跳跃
- 镜头呼吸感和行走缓动
- 基础墙体、箱子、场景碰撞
- 敌人刷新与警戒追击
- 四种敌人随机刷新
- 四种敌人模型、走路动画、挥砍攻击动画和受击反馈
- 敌人头顶血条
- 玩家掉血与 HUD 血量反馈
- 敌人受击、死亡和击杀统计
- 三把可切换武器：AK-47、SCAR-H、Dragon Sniper
- 鼠标左键开火
- 枪口闪光和简单后坐力
- 命中墙面 / 地面后的武器专属子弹印记
- 子弹印记数秒后自动淡出
- 不同武器使用不同枪声音效
- 角色脚步声与跳跃音效
- HUD、准星、暂停菜单和游戏帮助页

当前版本还没有加入：

- 换弹
- 真正的弹药消耗逻辑
- 环境音效
- 更完整的玩家受击特效和死亡演出

## 当前默认开局

当前默认开局配置在：

- `src/game/content/gameSelection.ts`

当前默认值是：

- 默认关卡：`dust2_classic`
- 默认武器：`weapon_001_ak47_classic`
- 当前可切换武器：`weapon_001_ak47_classic`、`weapon_002_scar_h_battle_rifle`、`weapon_003_red_dragon_tech_sniper`
- 当前启用敌人：4 种敌人全部启用
- 开局状态：暂停界面

也就是说，你现在启动项目后，默认就是 AK。
如果想切成别的武器开局，修改 `ACTIVE_WEAPON_ID` 即可。

## 当前武器

当前项目已经接入三把枪：

- `weapon_001_ak47_classic`
  名称：AK-47
  模型：`素材/武器/枪/枪01/枪的模型/model.glb`
  音效：`素材/武器/枪/枪01/枪的音效/枪声.mp3`
  伤害：身体 `50`，爆头 `100`
- `weapon_002_scar_h_battle_rifle`
  名称：SCAR-H
  模型：`素材/武器/枪/枪02/枪的模型/model.glb`
  音效：`素材/武器/枪/枪02/枪的音效/枪声.mp3`
  伤害：身体 `70`，爆头 `140`
- `weapon_003_red_dragon_tech_sniper`
  名称：Dragon Sniper
  模型：`素材/武器/枪/枪03/枪的模型/model.glb`
  音效：`素材/武器/枪/枪03/枪的音效/枪声.mp3`
  伤害：身体 `120`，爆头 `220`

当前切枪规则：

- 运行时按数字键 `1`，会在 `EQUIPPED_WEAPON_IDS` 里的武器之间循环切换。

如果你想设置开局默认拿哪把枪，改这里：

- `src/game/content/gameSelection.ts`
  修改 `ACTIVE_WEAPON_ID`

如果你想控制按数字键 `1` 时会轮换哪些枪，改这里：

- `src/game/content/gameSelection.ts`
  修改 `EQUIPPED_WEAPON_IDS`

## 当前敌人

当前项目已经接入四种敌人：

- `enemy_001_raider`
  名称：Raider
  生命值：`200`
  伤害：`16`
  模型：`素材/敌人/敌人01/敌人模型/model.glb`
- `enemy_002_tree_brute`
  名称：Tree Brute
  生命值：`500`
  伤害：`50`
  模型：`素材/敌人/敌人02/敌人模型/model.glb`
- `enemy_003_tree_guardian`
  名称：Tree Guardian
  生命值：`350`
  伤害：`32`
  模型：`素材/敌人/敌人03/敌人模型/model.glb`
- `enemy_004_rotwood_overlord`
  名称：Rotwood Overlord
  生命值：`700`
  伤害：`55`
  模型：`素材/敌人/敌人04/敌人模型/model.glb`

行为说明：

- 场景中会刷新多名敌人
- 四种敌人当前会随机生成
- 当你进入敌人的警戒范围后，敌人会朝玩家移动
- 敌人靠近后会挥砍攻击
- 敌人挥砍命中后会扣除玩家血量
- 敌人受击后会掉血，死亡后会进入尸体保留阶段，再被清理

## 启动项目

### 1. 安装依赖

如果你是第一次启动项目，在项目根目录执行：

```bash
npm install
```

### 2. 可选：先构建一次

```bash
npm run build
```

### 3. 启动开发服务器

执行：

```bash
npm run start
```

你也可以用：

```bash
npm run dev
```

启动后，终端会显示一个本地地址，通常是：

```text
http://localhost:5173/
```

用浏览器打开这个地址，就可以进入游戏。

如果 `5173` 端口被占用，Vite 会自动换一个端口，按终端里显示的地址打开即可。

## 开始试玩

进入页面后，按下面步骤测试：

1. 打开浏览器里的游戏页面。
2. 开局会默认加载第一关，并停在暂停界面。
3. 点击暂停界面的“进入战场”按钮开始游戏。
4. 鼠标会锁定到游戏窗口。
5. 使用 `WASD` 移动。
6. 按住 `Shift` 冲刺。
7. 按 `Space` 跳跃。
8. 按数字键 `1` 切枪。
9. 移动鼠标观察四周。
10. 按住鼠标左键连续开火。
11. 按 `Esc` 会退出鼠标锁定，并重新打开暂停界面。
12. 暂停界面可以：
    - 继续游戏
    - 重启本关卡
    - 展开关卡列表并切换关卡
    - 打开游戏帮助查看当前键位说明

方向说明：

- `W`：前进
- `A`：左移
- `S`：后退
- `D`：右移
- `Shift`：冲刺
- `Space`：跳跃
- `Mouse`：观察
- `Mouse Left`：开火
- `1`：切枪
- `Esc`：暂停并释放鼠标

## 当前推荐测试点

每次启动后，建议先测这几项：

1. 页面是否正常加载出 3D 场景。
2. 开局是否默认停在暂停界面，而不是直接进入战斗。
3. 点击“进入战场”后，鼠标是否成功锁定。
4. 游戏中按 `Esc` 后，是否会重新打开暂停界面。
5. 暂停界面的“重启本关卡”是否会正确重开当前关卡。
6. 暂停界面的“选择关卡”是否可以切到另一张图。
7. 暂停界面的“游戏帮助”是否能正常打开帮助页。
8. 帮助页里是否能看到移动、跳跃、切枪、暂停等键位说明。
9. `WASD` 是否能正常移动。
10. 按住 `Shift` 时，移动速度是否明显提升。
11. 按 `Space` 后是否能立刻起跳，并在约 1 秒内完成起跳到落地。
12. 跳跃过程中是否不会播放脚步声。
13. 跳跃时是否能跨过一部分较低障碍。
14. 玩家是否会被墙体和箱子挡住，不会穿模。
15. 场景中是否能看到刷新的敌人。
16. 敌人是否会随机出现四种类型。
17. 接近敌人后，敌人是否会进入警戒并朝玩家追击。
18. 四种敌人移动、攻击、受击、死亡动画是否正常播放。
19. 敌人头顶是否显示血条，并随受击正确减少。
20. HUD 是否会实时显示玩家血量、剩余敌人数和击杀数。
21. 站立不动时，镜头是否有轻微呼吸感。
22. 行走和冲刺时，镜头是否有自然的缓动与上下起伏。
23. 行走时脚步声是否正常触发。
24. 开火时是否能听到当前武器对应的枪声音效。
25. 开火时是否能看到枪口闪光。
26. 开火时镜头和武器是否有轻微后坐力反馈。
27. 默认 AK-47 开局时，Raider 是否约 4 枪身体击杀、约 2 枪爆头击杀。
28. 默认 AK-47 开局时，Tree Brute 是否约 10 枪身体击杀、约 5 枪爆头击杀。
29. 默认 AK-47 开局时，Tree Guardian 是否约 7 枪身体击杀、约 4 枪爆头击杀。
30. 默认 AK-47 开局时，Rotwood Overlord 是否约 14 枪身体击杀、约 7 枪爆头击杀。
31. 按数字键 `1` 切到 SCAR-H 后，武器模型、音效、HUD 名称是否正确切换。
32. SCAR-H 下，Raider 是否约 3 枪身体击杀、约 2 枪爆头击杀。
33. SCAR-H 下，Tree Brute 是否约 8 枪身体击杀、约 4 枪爆头击杀。
34. SCAR-H 下，Tree Guardian 是否约 5 枪身体击杀、约 3 枪爆头击杀。
35. SCAR-H 下，Rotwood Overlord 是否约 10 枪身体击杀、约 5 枪爆头击杀。
36. 再次按数字键 `1` 切到 Dragon Sniper 后，武器模型、音效、HUD 名称是否正确切换。
37. Dragon Sniper 下，Raider 是否约 2 枪身体击杀、约 1 枪爆头击杀。
38. Dragon Sniper 下，Tree Brute 是否约 5 枪身体击杀、约 3 枪爆头击杀。
39. Dragon Sniper 下，Tree Guardian 是否约 3 枪身体击杀、约 2 枪爆头击杀。
40. Dragon Sniper 下，Rotwood Overlord 是否约 6 枪身体击杀、约 4 枪爆头击杀。
41. 子弹命中墙面或地面后，是否会出现当前武器对应的命中印记。
42. 三把武器的命中印记外观是否明显不同。
43. 子弹印记是否会在数秒后逐渐淡出消失。

## 生产模式预览

如果你想用接近发布版的方式测试：

### 1. 构建项目

```bash
npm run build
```

### 2. 启动预览服务器

```bash
npm run preview
```

默认会输出一个预览地址，通常是：

```text
http://localhost:4173/
```

## 常见问题

### 页面打不开

- 先确认终端里 `npm run start` 没有报错。
- 确认你打开的是终端里实际输出的地址。

### 鼠标不能转动视角

- 先点击暂停界面的“进入战场”按钮。
- 如果鼠标已经释放，重新点击游戏画面。

### 鼠标左键不能开火

- 先确认鼠标已经锁定进游戏。
- 当前版本需要鼠标锁定后，左键才会进入开火状态。
- 当前版本已经接入敌人命中和伤害结算，以及世界表面命中印记。

### 没有脚步声

- 先点击暂停界面的“进入战场”，浏览器通常需要用户先与页面交互，才允许播放音频。
- 确认系统没有静音，浏览器标签页也没有被静音。
- 当前脚步声素材使用的是 `素材/角色/脚步声01.mp3`。

### 没有枪声

- 先确认鼠标已经锁定进游戏并实际开火。
- AK-47 枪声素材使用的是 `素材/武器/枪/枪01/枪的音效/枪声.mp3`。
- SCAR-H 枪声素材使用的是 `素材/武器/枪/枪02/枪的音效/枪声.mp3`。
- Dragon Sniper 枪声素材使用的是 `素材/武器/枪/枪03/枪的音效/枪声.mp3`。
- 如果浏览器刚打开页面还没交互过，先点击“进入战场”再测试。

### 跳跃没有反应

- 先确认鼠标已经锁定进游戏。
- 当前跳跃按键是 `Space`。
- 跳跃音效素材使用的是 `素材/角色/跳跃01.mp3`。

### 敌人没有追击

- 先主动向前推进，进入敌人的警戒范围。
- 当前版本敌人使用的是基础追击逻辑，不带复杂寻路。
- 当前版本敌人的挥砍已接玩家掉血。

### 没看到某一种敌人

- 当前四种敌人都是随机生成，不是每个出生点都固定出现。
- 首次进入页面时，模型会先进行一次本地加载。
- 如果想强制只测某一种敌人，改 `src/game/content/gameSelection.ts` 里的 `ENABLED_ENEMY_IDS`。

### 敌人打不死

- 当前默认开局武器是 AK-47。
- 按数字键 `1` 会在 AK-47、SCAR-H、Dragon Sniper 之间循环切换。
- 子弹命中会受场景障碍阻挡，隔着箱子或墙体不会穿透击杀。
- 如果墙面或地面出现了命中印记，说明这枪打到了世界表面，而不是敌人。

### 角色不能移动

- 先确认鼠标已经锁定进游戏。
- 输入法如果抢占按键，先切回英文输入状态再测试。

## 项目结构

核心文件：

- `src/main.ts`：浏览器入口，负责创建并启动 `GameDirector`
- `src/game/GameDirector.ts`：应用层总控，负责默认开局、暂停、重开、选关和切换整局游戏
- `src/game/GameApp.ts`：单局游戏运行时，负责把场景、玩家、敌人、武器、HUD、音频装配起来
- `src/game/content/gameSelection.ts`：默认关卡、默认武器、已装备武器列表、启用敌人列表
- `src/game/content/ui/gameHelpContent.ts`：暂停菜单帮助页的键位说明和文案内容
- `src/game/config/systemTuning.ts`：系统级调参总入口
- `src/game/content/levels/levelCatalog.ts`：关卡注册表与暂停菜单展示文案
- `src/game/world/shared/desertWorldKit.ts`：地图共享搭建工具
- `src/game/world/levels/dust2_classic/index.ts`：第一关 Dust2 场景入口
- `src/game/world/levels/dust2_classic/layout.ts`：第一关布局与碰撞
- `src/game/world/levels/dust2_classic/worldData.ts`：第一关出生点与刷怪点
- `src/game/world/levels/desert_fortress/index.ts`：第二关 Desert Fortress 场景入口
- `src/game/world/levels/desert_fortress/layout.ts`：第二关布局与碰撞
- `src/game/world/levels/desert_fortress/worldData.ts`：第二关出生点与刷怪点
- `src/game/player/PlayerController.ts`：玩家移动、视角、跳跃和碰撞
- `src/game/input/InputController.ts`：键盘、鼠标、指针锁定输入
- `src/game/content/weapons/weaponCatalog.ts`：武器注册表与当前武器配置
- `src/game/weapons/WeaponTypes.ts`：武器配置和视图模型接口
- `src/game/weapons/models/AK47ViewModel.ts`：AK-47 第一人称武器模型、开火、枪口闪光和后坐力
- `src/game/weapons/models/ScarHViewModel.ts`：SCAR-H 第一人称武器模型与动画接入
- `src/game/weapons/models/RedDragonSniperViewModel.ts`：Dragon Sniper 第一人称武器模型与动画接入
- `src/game/combat/ShotResolver.ts`：射击命中结算入口，判断命中敌人还是世界表面
- `src/game/effects/BulletImpactSystem.ts`：子弹印记生成、保留和淡出
- `src/game/enemies/EnemyHealthBar.ts`：敌人头顶血条
- `src/game/content/enemies/enemyCatalog.ts`：敌人的纯配置定义
- `src/game/enemies/EnemyRuntimeCatalog.ts`：敌人配置与视觉工厂的运行时装配
- `src/game/enemies/EnemyController.ts`：单个敌人的警戒、追击和攻击状态机
- `src/game/enemies/EnemyManager.ts`：敌人刷新与统一更新
- `src/game/enemies/models/RaiderModel.ts`：Raider 的 glb 模型与动画接入
- `src/game/enemies/models/TreeBruteModel.ts`：Tree Brute 的 glb 模型与动画接入
- `src/game/enemies/models/TreeGuardianModel.ts`：Tree Guardian 的 glb 模型与动画接入
- `src/game/enemies/models/RotwoodOverlordModel.ts`：Rotwood Overlord 的 glb 模型与动画接入
- `src/game/audio/FootstepAudio.ts`：脚步声音效播放与播放器池
- `src/game/audio/JumpAudio.ts`：跳跃音效播放
- `src/game/audio/GunfireAudio.ts`：通用枪声音效播放
- `src/game/ui/Hud.ts`：战斗 HUD、血量、击杀数、敌人数和准星展示
- `src/game/ui/PauseMenu.ts`：开局暂停界面、继续、重开、选关、游戏帮助 UI

## 文档维护说明

这份 `README.md` 会持续维护。
以后只要新增了玩法、操作、测试流程、启动方式或配置结构，都应该同步更新这里。
