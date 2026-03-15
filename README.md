# TTTTV-config

Moovie 远程资源站配置仓库。

## 入口文件（后端会依次尝试）

1. `sources.json`
2. `index.json`
3. `indexes/all.json`

只要其中任意一个存在且是合法 JSON 即可。

## `sources.json` 格式

```json
{
  "sources": [
    {
      "key": "example.com",
      "name": "🎬示例",
      "api": "https://example.com/api.php/provide/vod",
      "detail": "https://example.com",
      "group": "影视",
      "r18": false,
      "_comment": "可选备注"
    }
  ]
}
```

R18 源请务必显式写：`"r18": true`，并建议 `group` 为 `"R18"`。
