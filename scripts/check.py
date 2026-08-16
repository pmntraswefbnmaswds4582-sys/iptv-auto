from urllib.request import Request, urlopen
from urllib.parse import urljoin
from pathlib import Path
import re
import time


INPUT_FILE = Path("output/discovered.json")
OUTPUT_DIR = Path("output")

TIMEOUT = 10

# 单个频道最多保留几个候选源
MAX_SOURCES_PER_CHANNEL = 3


# ============================================================
# HTTP 请求
# ============================================================

def fetch(url, timeout=TIMEOUT):

    request = Request(
        url,
        headers={
            "User-Agent": "iptv-auto/1.0"
        }
    )

    start = time.monotonic()

    with urlopen(
        request,
        timeout=timeout
    ) as response:

        data = response.read()

        elapsed = time.monotonic() - start

        return (
            data.decode(
                "utf-8",
                errors="ignore"
            ),
            elapsed
        )


# ============================================================
# 判断是否为 M3U8
# ============================================================

def is_m3u8(text):

    return (
        "#EXTM3U" in text
        or "#EXT-X-" in text
    )


# ============================================================
# 提取分辨率
# ============================================================

def get_resolutions(text):

    results = []

    matches = re.findall(
        r'RESOLUTION=(\d+)x(\d+)',
        text,
        re.IGNORECASE
    )

    for width, height in matches:

        results.append(
            (
                int(width),
                int(height)
            )
        )

    return results


# ============================================================
# 判断是否真 4K
# ============================================================

def is_real_4k(resolutions):

    for width, height in resolutions:

        if (
            width >= 3840
            and height >= 2160
        ):

            return True

    return False


# ============================================================
# 找 Master Playlist 中的子播放列表
# ============================================================

def find_variant_playlists(
    playlist_url,
    text
):

    variants = []

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for index, line in enumerate(lines):

        if (
            line.startswith("#EXT-X-STREAM-INF")
            and index + 1 < len(lines)
        ):

            next_line = lines[index + 1]

            if not next_line.startswith("#"):

                variants.append(
                    urljoin(
                        playlist_url,
                        next_line
                    )
                )

    return variants


# ============================================================
# 检测直播分片
# ============================================================

def check_segments(
    playlist_url,
    text
):

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    segment_urls = []

    for line in lines:

        if line.startswith("#"):
            continue

        if (
            line.startswith("http://")
            or line.startswith("https://")
        ):

            segment_urls.append(line)

        else:

            segment_urls.append(
                urljoin(
                    playlist_url,
                    line
                )
            )

    # 只检测最后几个分片
    segment_urls = segment_urls[-3:]

    if not segment_urls:

        return False

    success = 0

    for segment in segment_urls:

        try:

            request = Request(
                segment,
                headers={
                    "User-Agent":
                        "iptv-auto/1.0"
                }
            )

            with urlopen(
                request,
                timeout=TIMEOUT
            ) as response:

                # 不需要下载完整视频
                response.read(1024)

                success += 1

        except Exception:

            pass

    return success >= 1


# ============================================================
# 检测单个源
# ============================================================

def check_source(channel):

    url = channel["url"]

    result = {
        "url": url,
        "name": channel["name"],
        "category": channel.get(
            "category",
            "其他"
        ),
        "reachable": False,
        "is_hls": False,
        "real_4k": False,
        "width": 0,
        "height": 0,
        "response_ms": 0,
        "segments_ok": False,
        "score": 0,
    }

    try:

        text, elapsed = fetch(url)

        result["reachable"] = True

        result["response_ms"] = int(
            elapsed * 1000
        )

        if not is_m3u8(text):

            # 有些地址不是标准 M3U8
            # 但 HTTP 本身可以访问
            result["score"] = 20

            return result

        result["is_hls"] = True

        resolutions = get_resolutions(
            text
        )

        if resolutions:

            width, height = max(
                resolutions,
                key=lambda x: x[0] * x[1]
            )

            result["width"] = width
            result["height"] = height

        # Master Playlist
        variants = find_variant_playlists(
            url,
            text
        )

        # 如果有 Master Playlist，
        # 继续检测最高分辨率子流
        if variants:

            variant_results = []

            for variant in variants:

                try:

                    variant_text, _ = fetch(
                        variant,
                        timeout=8
                    )

                    variant_resolutions = (
                        get_resolutions(
                            text
                        )
                    )

                    variant_results.extend(
                        variant_resolutions
                    )

                    # 找最高分辨率
                    if variant_resolutions:

                        w, h = max(
                            variant_resolutions,
                            key=lambda x:
                            x[0] * x[1]
                        )

                        if (
                            w * h
                            >
                            result["width"]
                            *
                            result["height"]
                        ):

                            result["width"] = w
                            result["height"] = h

                except Exception:

                    pass

        result["real_4k"] = (
            result["width"] >= 3840
            and result["height"] >= 2160
        )

        # 检测媒体分片
        result["segments_ok"] = (
            check_segments(
                url,
                text
            )
        )

        # ====================================================
        # 评分
        # ====================================================

        score = 0

        if result["reachable"]:
            score += 20

        if result["is_hls"]:
            score += 20

        if result["segments_ok"]:
            score += 30

        if result["real_4k"]:
            score += 25

        elif result["width"] >= 1920:
            score += 15

        elif result["width"] >= 1280:
            score += 8

        # 响应速度
        if result["response_ms"] <= 1000:
            score += 5

        elif result["response_ms"] <= 2500:
            score += 3

        result["score"] = score

        return result

    except Exception as error:

        print(
            f"[失败] {channel['name']}"
        )

        print(
            f"       {url}"
        )

        print(
            f"       {error}"
        )

        return result


# ============================================================
# 写 M3U
# ============================================================

def write_m3u(
    filename,
    channels
):

    lines = [
        "#EXTM3U"
    ]

    for channel in channels:

        name = channel["name"]

        category = channel.get(
            "category",
            "其他"
        )

        tvg_id = channel.get(
            "tvg_id",
            ""
        )

        logo = channel.get(
            "logo",
            ""
        )

        width = channel.get(
            "width",
            0
        )

        height = channel.get(
            "height",
            0
        )

        if width and height:

            display_name = (
                f"{name} "
                f"({width}x{height})"
            )

        else:

            display_name = name

        lines.append(
            f'#EXTINF:-1 '
            f'tvg-id="{tvg_id}" '
            f'tvg-logo="{logo}" '
            f'group-title="{category}",'
            f'{display_name}'
        )

        lines.append(
            channel["url"]
        )

    filename.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )

    print(
        f"[生成] {filename}"
    )

    print(
        f"       {len(channels)} 个源"
    )


# ============================================================
# 主程序
# ============================================================

def main():

    if not INPUT_FILE.exists():

        raise SystemExit(
            "找不到 output/discovered.json"
        )

    data = INPUT_FILE.read_text(
        encoding="utf-8"
    )

    import json

    parsed = json.loads(data)

    channels = parsed.get(
        "channels",
        []
    )

    print(
        f"[候选源] {len(channels)}"
    )

    checked = []

    # ========================================================
    # 检测
    # ========================================================

    for index, channel in enumerate(
        channels,
        start=1
    ):

        print(
            f"[{index}/{len(channels)}] "
            f"{channel['name']}"
        )

        result = check_source(
            channel
        )

        if result["reachable"]:

            merged = dict(channel)

            merged.update(result)

            checked.append(
                merged
            )

    print(
        f"[可访问] {len(checked)}"
    )

    # ========================================================
    # 按频道名称分组
    # ========================================================

    grouped = {}

    for channel in checked:

        key = (
            channel["name"]
            .strip()
            .lower()
        )

        grouped.setdefault(
            key,
            []
        ).append(channel)

    best_channels = []

    # ========================================================
    # 每个频道选择最佳源
    # ========================================================

    for name, candidates in grouped.items():

        candidates.sort(
            key=lambda x: (
                x["real_4k"],
                x["score"],
                x["width"],
                x["height"],
                -x["response_ms"]
            ),
            reverse=True
        )

        best_channels.append(
            candidates[0]
        )

    # ========================================================
    # 分类
    # ========================================================

    cctv_4k = [
        x
        for x in best_channels
        if x["real_4k"]
        and (
            "CCTV"
            in x["name"].upper()
        )
    ]

    cctv_hd = [
        x
        for x in best_channels
        if (
            "CCTV"
            in x["name"].upper()
        )
        and not x["real_4k"]
        and x["width"] >= 1280
    ]

    phoenix = [
        x
        for x in best_channels
        if x["category"]
        == "凤凰卫视"
    ]

    guangdong = [
        x
        for x in best_channels
        if x["category"]
        == "广东"
    ]

    sports = [
        x
        for x in best_channels
        if x["category"]
        == "体育"
    ]

    hongkong = [
        x
        for x in best_channels
        if x["category"]
        == "香港"
    ]

    macau = [
        x
        for x in best_channels
        if x["category"]
        == "澳门"
    ]

    taiwan = [
        x
        for x in best_channels
        if x["category"]
        == "台湾"
    ]

    # ========================================================
    # BEST
    #
    # 真4K优先
    # 但低分4K不能进入
    # ========================================================

    best = sorted(
        best_channels,
        key=lambda x: (
            x["score"],
            x["real_4k"],
            x["width"],
            x["height"]
        ),
        reverse=True
    )

    # ========================================================
    # 输出
    # ========================================================

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    write_m3u(
        OUTPUT_DIR / "best.m3u",
        best
    )

    write_m3u(
        OUTPUT_DIR / "cctv_4k.m3u",
        cctv_4k
    )

    write_m3u(
        OUTPUT_DIR / "cctv_hd.m3u",
        cctv_hd
    )

    write_m3u(
        OUTPUT_DIR / "phoenix.m3u",
        phoenix
    )

    write_m3u(
        OUTPUT_DIR / "guangdong.m3u",
        guangdong
    )

    write_m3u(
        OUTPUT_DIR / "sports.m3u",
        sports
    )

    write_m3u(
        OUTPUT_DIR / "hongkong.m3u",
        hongkong
    )

    write_m3u(
        OUTPUT_DIR / "macau.m3u",
        macau
    )

    write_m3u(
        OUTPUT_DIR / "taiwan.m3u",
        taiwan
    )

    # ========================================================
    # 保存检测报告
    # ========================================================

    report = {
        "generated_at": int(time.time()),
        "candidate_count": len(channels),
        "reachable_count": len(checked),
        "best_count": len(best_channels),
        "real_4k_count": len(cctv_4k),
        "channels": checked,
    }

    (OUTPUT_DIR / "check_report.json").write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("")
    print("==============================")
    print(" IPTV 检测完成")
    print("==============================")
    print(
        f"候选：{len(channels)}"
    )
    print(
        f"可访问：{len(checked)}"
    )
    print(
        f"最终频道：{len(best_channels)}"
    )
    print(
        f"真4K：{len(cctv_4k)}"
    )


if __name__ == "__main__":

    main()
