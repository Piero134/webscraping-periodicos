import requests, json

q = json.dumps({
    "section": "/politica",
    "feedOffset": 0,
    "stories_qty": 3
})
r = requests.get(
    "https://elcomercio.pe/pf/api/v3/content/fetch/story-feed-by-section",
    params={"query": q, "_website": "elcomercio"}
)
data = r.json()
print(json.dumps(data["content_elements"][0], indent=2, ensure_ascii=False))
