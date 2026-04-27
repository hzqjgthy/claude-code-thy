rm -rf .git

第一次提交：

git init

git config --global user.email "274579....@qq.com" 

git config --global user.name "hzqjgthy"

git add . 

git commit -m "11111"  

git remote add origin https://github.com/hzqjgthy/FPS.git


git push -u origin main


后续提交：

git add .

git commit -m "提交说明"

git push

git push -u origin main --force




# 临时启用代理（仅当前终端会话）
export https_proxy=http://127.0.0.1:7890
export http_proxy=http://127.0.0.1:7890

# 取消代理
unset https_proxy http_proxy


切换分支到 front_and_back
git switch -c front_and_back
git branch -u origin/front_and_back

切回 main
git switch main
查看当前分支情况 git branch -vv