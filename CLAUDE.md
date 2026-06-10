# 湾区买房指南 — 项目规范

## ZIP Block 结构规范

新增任何 ZIP 区块，必须严格使用 `scripts/zip_block_template.html` 的结构。

**5 项统计缺一不可，zlabel 文字不可修改：**

```html
<div class="zstat"><span class="zval up">$X.XXM</span><span class="zlabel">中位成交价</span></div>
<div class="zstat"><span class="zval up">↑X.X%</span><span class="zlabel">同比涨幅</span></div>
<div class="zstat"><span class="zval neutral">XX天</span><span class="zlabel">平均成交</span></div>
<div class="zstat"><span class="zval school">★★★★☆</span><span class="zlabel">学区评级</span></div>
<div class="zstat"><span class="zval neutral">100%</span><span class="zlabel">成交/要价比</span></div>
```

> ① 中位成交价 和 ② 同比涨幅 由 `patch_html.py` 每日自动覆盖。  
> ③ 平均成交、④ 学区评级、⑤ 成交/要价比 手动维护，patcher 不会触碰。

**zlabel 精确匹配是自动更新的前提，任何别名（城市中位价、全市中位价、西侧学区 等）都会导致 patcher 跳过该字段。**

## 其他子元素规范

每个 zip-block 还必须包含：
- `zip-school-note` — 学校名称 + GreatSchools 评分
- `zip-commute` — 高速/Caltrain + 到各大公司车程
- `zip-profile` — 典型住户画像 + 年收入区间
- `listing-row` — 至少 1 张 listing-card

## 数据更新流程

1. `python3 scripts/update_listings.py` — 拉取 Zillow ZHVI，生成 `data/latest.json`
2. `python3 scripts/patch_html.py` — 将 latest.json 写入 index.html（只更新 ① ②）
3. `cp index.html 房产规划总结.html` — 保持两文件同步
4. GitHub Actions 每日 08:00 UTC 自动执行以上三步

## Tier 分级标准

| Tier | 价格区间 | zip-block class |
|------|---------|-----------------|
| 1    | $2.8M+  | t1              |
| 2    | $1.6–2.8M | t2            |
| 3    | $0.9–1.6M | t3            |
| 4    | <$0.9M  | t4              |

`"pin": True` 的 ZIP 不会触发 tier alert，即使 ZHVI 数据建议变更。

## 验证方法

添加新 block 后，运行以下命令确认结构完整：

```bash
python3 - << 'EOF'
import re
with open('index.html', encoding='utf-8') as f:
    html = f.read()
blocks = list(re.finditer(r'<div class="zip-block"[^>]*>', html))
required = ['中位成交价', '同比涨幅', '平均成交', '学区评级', '成交/要价比']
missing = []
for i, m in enumerate(blocks):
    start = m.start()
    end = blocks[i+1].start() if i+1 < len(blocks) else len(html)
    block = html[start:end]
    zip_m = re.search(r'<span class="zip-code">([^<]+)</span>', block)
    zc = zip_m.group(1) if zip_m else f'block_{i}'
    miss = [l for l in required if l not in block]
    if miss:
        missing.append(f'  ✗ {zc}: {miss}')
print('\n'.join(missing) if missing else f'✓ All {len(blocks)} blocks OK')
EOF
```
