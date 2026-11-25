from .conftest import connect, create_post, submit

PNG = b"\x89PNG\r\n\x1a\ntemplate"


def upload(client, name="品牌底圖"):
    resp = client.post("/api/templates", files={"file": ("bg.png", PNG, "image/png")}, data={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_upload_list_delete_and_owner_scope(client, other):
    tpl = upload(client)
    assert tpl["name"] == "品牌底圖" and "/templates/" in tpl["storage_path"]
    assert [t["id"] for t in client.get("/api/templates").json()] == [tpl["id"]]
    assert other.get("/api/templates").json() == []
    assert other.delete(f"/api/templates/{tpl['id']}").status_code == 404
    bad = client.post("/api/templates", files={"file": ("a.gif", b"GIF", "image/gif")})
    assert bad.status_code == 422
    assert client.delete(f"/api/templates/{tpl['id']}").status_code == 204
    assert client.get("/api/templates").json() == []


def test_post_with_template_skips_ai_image(client):
    tpl = upload(client)
    post = create_post(client, template_id=tpl["id"], layout="bottom")
    assert post["status"] == "editing"
    canvas = post["canvas_json"]
    assert canvas["template_id"] == tpl["id"] and canvas["image"]["url"] == tpl["public_url"]
    assert [i["source"] for i in post["images"]] == ["template"]
    # template counts as the image for Instagram
    connect(client, "instagram")
    assert submit(client, post["id"], ["instagram"]).status_code == 200


def test_unknown_or_foreign_template_falls_back_to_ai_background(client, other):
    """BUG-15: a deleted (or someone else's) template no longer fails the post: AI background + note."""
    tpl = upload(other)
    body = {"goal": "x", "selected": {"title": "t", "angle": "a", "hook": "h"}, "template_id": tpl["id"]}
    resp = client.post("/api/posts", json=body)
    assert resp.status_code == 202 and resp.json()["notices"] == ["這張模板已經刪除，改用 AI 底圖"]
    post = client.get(f"/api/posts/{resp.json()['id']}").json()
    assert post["status"] == "editing"
    assert post["canvas_json"]["template_id"] is None and post["canvas_json"]["image_note"] == "這張模板已經刪除，改用 AI 底圖"
    assert [i["source"] for i in post["images"]] == ["generated"]
    assert tpl["public_url"] not in str(post)  # nothing of the other user's template leaks


def test_regenerate_keeps_or_drops_template(client):
    tpl = upload(client)
    post = create_post(client, template_id=tpl["id"])
    client.delete(f"/api/templates/{tpl['id']}")  # removed from picker; existing post keeps it
    client.post(f"/api/posts/{post['id']}/generate", json={})
    kept = client.get(f"/api/posts/{post['id']}").json()
    assert kept["canvas_json"]["template_id"] == tpl["id"]
    client.post(f"/api/posts/{post['id']}/generate", json={"template_id": None})
    dropped = client.get(f"/api/posts/{post['id']}").json()
    assert dropped["canvas_json"]["template_id"] is None
    assert dropped["images"][-1]["source"] == "generated"
