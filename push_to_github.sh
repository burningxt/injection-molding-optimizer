#!/bin/bash
# 注塑成型项目 GitHub 推送脚本

set -e

echo "=========================================="
echo "  GitHub 项目推送脚本"
echo "=========================================="
echo ""

# 检查 Token
if [ ! -f /tmp/gh_token.txt ]; then
    echo "请先运行以下命令输入你的 GitHub Token:"
    echo ""
    echo "  read -s TOKEN && echo \"\$TOKEN\" > /tmp/gh_token.txt"
    echo ""
    echo "输入 Token 后按回车（输入不会显示）"
    exit 1
fi

GITHUB_TOKEN=$(cat /tmp/gh_token.txt)
GITHUB_USERNAME=""
REPO_NAME="injection-molding-optimizer"

# 获取用户名
echo -n "请输入你的 GitHub 用户名: "
read GITHUB_USERNAME

if [ -z "$GITHUB_USERNAME" ]; then
    echo "错误: 用户名不能为空"
    exit 1
fi

echo ""
echo "开始执行..."
echo "用户名: $GITHUB_USERNAME"
echo "仓库名: $REPO_NAME"
echo ""

# 1. 创建仓库
echo "[1/5] 在 GitHub 创建仓库..."
HTTP_STATUS=$(curl -s -o /tmp/gh_response.json -w "%{http_code}" \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    -X POST \
    -d "{\"name\":\"$REPO_NAME\",\"description\":\"基于贝叶斯优化的注塑成型工艺参数智能推荐系统\",\"private\":false}" \
    https://api.github.com/user/repos)

if [ "$HTTP_STATUS" -eq 201 ]; then
    echo "      ✓ 仓库创建成功"
elif [ "$HTTP_STATUS" -eq 422 ]; then
    echo "      ℹ 仓库可能已存在，继续执行..."
else
    echo "      ✗ 创建仓库失败 (HTTP $HTTP_STATUS)"
    cat /tmp/gh_response.json
    exit 1
fi

# 2. 配置 git
echo "[2/5] 配置 git 认证..."
git config --local credential.helper "store --file=/tmp/git-credentials"
echo "https://oauth:$GITHUB_TOKEN@github.com" > /tmp/git-credentials
echo "      ✓ git 认证已配置"

# 3. 重命名分支
echo "[3/5] 重命名分支 master → main..."
git branch -m main 2>/dev/null || true
echo "      ✓ 分支已重命名"

# 4. 添加远程仓库
echo "[4/5] 配置远程仓库..."
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/$GITHUB_USERNAME/$REPO_NAME.git"
echo "      ✓ 远程仓库已配置"

# 5. 提交并推送
echo "[5/5] 提交并推送到 GitHub..."

# 查看当前状态
echo ""
echo "当前更改:"
git status --short

# 提交
git add -A
git commit -m "更新配置文件和数据记录

- 更新 .claude/settings.local.json
- 更新初始试模清单数据
- 更新第1批次建议参数" || echo "提交可能已完成或没有更改可提交"

# 推送
git push -u origin main

echo ""
echo "=========================================="
echo "  ✓ 推送成功！"
echo "=========================================="
echo ""
echo "仓库地址: https://github.com/$GITHUB_USERNAME/$REPO_NAME"
echo ""

# 清理
rm -f /tmp/gh_token.txt /tmp/git-credentials /tmp/gh_response.json
git config --local --unset credential.helper 2>/dev/null || true

echo "已清理临时文件"
