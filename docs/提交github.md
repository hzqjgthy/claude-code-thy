rm -rf .git     （windows：Remove-Item -Recurse -Force .git）

第一次提交：

git init

git config --global user.email "274579....@qq.com" 

git config --global user.name "hzqjgthy"

或 gh auth login

git add . 

git commit -m "11111"  

git remote add origin https://github.com/hzqjgthy/claude-code-haha.git


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



给 Git 配置代理
git config --global http.proxy http://127.0.0.1:7890
git config --global https.proxy http://127.0.0.1:7890
清除代理
git config --global --unset http.proxy
git config --global --unset https.proxy

