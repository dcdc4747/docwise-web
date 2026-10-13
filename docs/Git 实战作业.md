# Git 实战作业（一步步跟着做）

看完尚硅谷 Git 入门视频，跟着这份作业**自己在电脑上走一遍**。第 1 遍可以在你自己的测试仓库里做；做完一遍后，再到 `docwise-web` 仓库里作为练习真正操作一次。

> **目标**：独立完成一次完整 PR 流程。做完后你就能独立认领任务、开发、提交了。
>
> **工具**：先装好 Git，并准备好你的 GitHub 账号（加入仓库后才有权限 push）。

---

## 作业 0：准备（10 分钟）

### 0.1 确认 Git 身份

Git 提交时会带上"你是谁"，这很重要。检查你当前的用户名和邮箱：

```bash
git config user.name
git config user.email
```

如果显示为空，或不是你的 GitHub 信息，就先设置（把 `xxx` 换成你自己的）：

```bash
git config --global user.name "你的GitHub用户名"
git config --global user.email "你GitHub账号绑定的邮箱"
```

> ⚠️ 这个项目里有多人协作，**身份一定要对**，否则提交会被算到别人头上。开工第一件事就是确认 `git config user.name`。

### 0.2 拉取仓库到本地

```bash
git clone https://github.com/<仓库名>/docwise-web.git
cd docwise-web
```

> 如果用 HTTPS 需要登录凭证；也可以改用 SSH（推荐，免密）。具体看你的 GitHub 账号配置。

---

## 作业 1：建分支（不可以直接在 main 上改）

### 1.1 先同步到最新

```bash
git checkout main
git pull
```

### 1.2 建自己的分支

分支名要能说明用途，千万别叫 `test`、`aaa`、`123` 这种。

```bash
git checkout -b docs/my-git-practice
```

命名规范：`feat/xxx`（功能）、`fix/xxx`（修复）、`docs/xxx`（文档）、`chore/xxx`（杂项）。

> ✅ **检查**：`git branch` 看到当前有 `*` 号的是你的新分支，就对了。

---

## 作业 2：改一个文件并提交

### 2.1 改点东西

打开仓库里的 README 或某个文件，随便加一行注释/说明并保存。这个作业我们只练流程，不要求改出什么功能。

### 2.2 看改了啥

```bash
git status        # 看哪些文件变了
git diff          # 看具体改了什么
```

### 2.3 暂存并提交

```bash
git add 文件名           # 只加这个文件；git add . 会把所有改动都加进去，小心别多加了
git commit -m "docs(my-git-practice): 我的第一次提交练习"
```

提交信息格式：`类型(范围): 说明`。范围如 `frontend` / `backend` / `repo` / `docs`。

> ✅ **检查**：`git log --oneline` 看到你刚提交的那一行。

---

## 作业 3：推上远程（push）

```bash
git push -u origin docs/my-git-practice
```

> `-u` 会把你的分支和远程关联起来，下次 `git push` 就不用带参数了。

看到"Everything up-to-date"或上传进度，就成功了。

---

## 作业 4：发一个 Pull Request（PR）

这一步通常是**在 GitHub 网页上做**，也可以跟着命令行推送后的提示链接点进去。

1. 打开仓库网页，GitHub 一般会在你 push 后提示 "Compare & pull request"。
2. 点 **New pull request**，确认：**base = main**，**compare = 你的分支**。
3. **写清描述**（很重要，这是你这次工作的小结）：
   - 做了什么
   - 怎么验证的（贴截图）
   - 参考/关联的 issue（如有）
4. 点 **Create pull request**。

> ✅ **检查**：网页上看到你的 PR，绿色可合并状态（或待审核）。这就完成了一次完整流程。

---

## 作业 5：同步别人最新的代码

自己开发期间，别人可能已经往 main 推了东西。**提交前先拉下来，避免冲突。**

```bash
git checkout main
git pull             # 拿到最新
git checkout 你的分支
git merge main       # 把最新代码合进你的分支（或 fetch+rebase）
```

---

## 作业 6（选做）：处理常见问题

### 6.1 提交到了 main 分支，怎么办？

没关系，把提交挪到新分支上：

```bash
git checkout -b feat/xxx     # 从当前状态新建一个正确分支
git checkout main            # 切回 main
# 回到 main 上把刚才的提交撤掉（--soft 保留改动在暂存区）
git reset --soft HEAD~1
```

### 6.2 想修改上一条提交信息？

```bash
git commit --amend -m "改后更清晰的信息"
```

### 6.3 找不想要又没提交的改动，想一键还原？

```bash
git checkout -- 文件名       # 丢弃某个文件的本地改动（谨慎，不可恢复）
```

---

## 结业自检（全勾 √ 就过关）

- [ ] `git config user.name` 是我的信息
- [ ] 我会 `git clone`、`git status`、`git diff`、`git log`
- [ ] 我看懂了：`add` / `commit` / `push` / `pull` 各干什么
- [ ] 我读得懂分支命名和最常用的提交信息格式
- [ ] 我**独立**走完一次 PR 全流程（建分支→改→提交→push→发 PR）
- [ ] 我知道"不能直接在 main 上改、必须开分支、PR 是唯一入口"

> ✅ 完成以上全部，你就可以去认领自己的任务卡，开始开发了。
>
> 记住三条铁律：**①不在 main 上直接改；②每次任务开新分支；③一定要推 PR，别只本地提交。**
