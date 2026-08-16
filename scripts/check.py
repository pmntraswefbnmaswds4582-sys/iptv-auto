from urllib.request import Request, urlopen
from urllib.parse import urljoin
from pathlib import Path
import json
import re
import time


INPUT_FILE = Path("output/discovered.json")
OUTPUT_DIR = Path("output")

# 单个源最多等待 3 秒
TIMEOUT = 3

# 每个频道最多保留 2 个候选源
MAX_CANDIDATES = 2


# ============================================================
# HTTP
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

        data = response.read(256000)

    elapsed = time.monotonic() - start

    return (
        data.decode(
            "utf-8",
            errors="ignore"
        ),
        int(elapsed * 1000)
    )


# ============================================================
# 分辨率
# ============================================================

def get_resolutions(text):

    result = []

    for width, height in re.findall(
        r'RESOLUTION=(\d+)x(\d+)',
        text,
        re.IGNORECASE
    ):

        result.append(
            (
                int(width),
                int(height)
            )
        )

    return result


# ============================================================
# Master Playlist
# ============================================================

def get_variants(url, text):

    lines = [
        x.strip()
        for x in text.splitlines()
        if x.strip()
    ]

    variants = []

    for i, line in enumerate(lines):

        if (
            line.startswith(
                "#EXT-X-STREAM-INF"
            )
            and i + 1 < len(lines)
        ):

            next_line = lines[i + 1]

            if not next_line.startswith("#"):

                variants.append(
                    urljoin(
                        url,
                        next_line
                    )
                )

    return variants


# ============================================================
# 频道是否值得检测
# ============================================================

def wanted_channel(channel):

    text = " ".join([
        channel.get("name", ""),
        channel.get("tvg_id", ""),
        channel.get("group", ""),
    ]).lower()

    keywords = [

        # CCTV
        "cctv",

        # 凤凰
        "凤凰",
        "鳳凰",
        "phoenix",

        # 广东
        "广东",
        "廣東",
        "guangdong",

        # 体育
        "体育",
        "體育",
        "sports",

        # 香港
        "香港",
        "hong kong",
        "hk",

        # 澳门
        "澳门",
        "澳門",
        "macau",
        "macao",

        # 台湾
        "台湾",
        "台灣",
        "taiwan",
    ]

    return any(
        keyword in text
        for keyword in keywords
    )


# ============================================================
# 检测单个源
# ============================================================

def check(channel):

    url = channel["url"]

    result = dict(channel)

    result["reachable"] = False
    result["hls"] = False
    result["width"] = 0
    result["height"] = 0
    result["real_4k"] = False
    result["response_ms"] = 0
    result["score"] = 0

    try:

        text, response_ms = fetch(url)

        result["reachable"] = True
        result["response_ms"] = response_ms

        # 不是 M3U8
        if "#EXTM3U" not in text:

            result["score"] = 20

            return result

        result["hls"] = True

        resolutions = get_resolutions(
            text
        )

        variants = get_variants(
            url,
            text
        )

        # Master Playlist
        # 只检查最多两个 Variant
        for variant in variants[:2]:

            try:

                variant_text, _ = fetch(
                    variant,
                    timeout=2
                )

                resolutions.extend(
                    get_resolutions(
                        variant_text
                    )
                )

            except Exception:

                pass

        # 选择最高分辨率
        if resolutions:

            width, height = max(
                resolutions,
                key=lambda x:
                x[0] * x[1]
            )

            result["width"] = width
            result["height"] = height

        # 真 4K
        if (
            result["width"] >= 3840
            and result["height"] >= 2160
        ):

            result["real_4k"] = True

        # ====================================================
        # 评分
        # ====================================================

        score = 0

        score += 20

        if result["hls"]:
            score += 25

        if result["real_4k"]:
            score += 40

        elif result["width"] >= 1920:
            score += 25

        elif result["width"] >= 1280:
            score += 15

        elif result["width"] >= 720:
            score += 5

        if result["response_ms"] <= 500:
            score += 15

        elif result["response_ms"] <= 1500:
            score += 10

        elif result["response_ms"] <= 2500:
            score += 5

        result["score"] = score

        return result

    except Exception:

        return result


# ============================================================
# M3U
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

        tvg_id = channel.get(
            "tvg_id",
            ""
        )

        logo = channel.get(
            "logo",
            ""
        )

        category = channel.get(
            "category",
            "其他"
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

            name = (
                f"{name} "
                f"({width}x{height})"
            )

        lines.append(
            f'#EXTINF:-1 '
            f'tvg-id="{tvg_id}" '
            f'tvg-logo="{logo}" '
            f'group-title="{category}",'
            f'{name}'
        )

        lines.append(
            channel["url"]
        )

    filename.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )


# ============================================================
# 主程序
# ============================================================

def main():

    print(
        "=============================="
    )

    print(
        " IPTV 快速直播源检测"
    )

    print(
        "=============================="
    )

    if not INPUT_FILE.exists():

        raise SystemExit(
            "找不到 discovered.json"
        )

    data = json.loads(
        INPUT_FILE.read_text(
            encoding="utf-8"
        )
    )

    all_channels = data.get(
        "channels",
        []
    )

    # --------------------------------------------------------
    # 只筛选目标频道
    # --------------------------------------------------------

    candidates = [
        channel
        for channel in all_channels
        if wanted_channel(channel)
    ]

    print(
        f"[全部源] {len(all_channels)}"
    )

    print(
        f"[目标源] {len(candidates)}"
    )

    # --------------------------------------------------------
    # 每个频道最多检测两个源
    # --------------------------------------------------------

    grouped = {}

    for channel in candidates:

        key = (
            channel["name"]
            .strip()
            .lower()
        )

        grouped.setdefault(
            key,
            []
        ).append(channel)

    selected = []

    for name, items in grouped.items():

        # 优先不同 URL
        seen = set()

        unique = []

        for item in items:

            if item["url"] in seen:
                continue

            seen.add(
                item["url"]
            )

            unique.append(item)

        # 最多两个
        selected.extend(
            unique[:MAX_CANDIDATES]
        )

    print(
        f"[实际检测] {len(selected)}"
    )

    # --------------------------------------------------------
    # 检测
    # --------------------------------------------------------

    checked = []

    for index, channel in enumerate(
        selected,
        start=1
    ):

        print(
            f"[检测 {index}/{len(selected)}] "
            f"{channel['name']}"
        )

        result = check(channel)

        if result["reachable"]:

            checked.append(result)

            print(
                f"  -> "
                f"{result['width']}x"
                f"{result['height']} "
                f"{result['response_ms']}ms "
                f"score={result['score']}"
            )

    # --------------------------------------------------------
    # 每频道选择最佳
    # --------------------------------------------------------

    best = {}

    for channel in checked:

        key = (
            channel["name"]
            .strip()
            .lower()
        )

        if (
            key not in best
            or channel["score"]
            > best[key]["score"]
        ):

            best[key] = channel

    best_channels = list(
        best.values()
    )

    # --------------------------------------------------------
    # 分类
    # --------------------------------------------------------

    cctv_4k = [
        x for x in best_channels
        if (
            "cctv"
            in x["name"].lower()
            and x["real_4k"]
        )
    ]

    cctv_hd = [
        x for x in best_channels
        if (
            "cctv"
            in x["name"].lower()
            and not x["real_4k"]
            and x["width"] >= 1280
        )
    ]

    phoenix = [
        x for x in best_channels
        if x.get("category")
        == "凤凰卫视"
    ]

    guangdong = [
        x for x in best_channels
        if x.get("category")
        == "广东"
    ]

    sports = [
        x for x in best_channels
        if x.get("category")
        == "体育"
    ]

    hongkong = [
        x for x in best_channels
        if x.get("category")
        == "香港"
    ]

    macau = [
        x for x in best_channels
        if x.get("category")
        == "澳门"
    ]

    taiwan = [
        x for x in best_channels
        if x.get("category")
        == "台湾"
    ]

    # --------------------------------------------------------
    # BEST
    # --------------------------------------------------------

    best_channels.sort(
        key=lambda x: (
            x["real_4k"],
            x["score"],
            x["width"],
            x["height"]
        ),
        reverse=True
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    write_m3u(
        OUTPUT_DIR / "best.m3u",
        best_channels
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

    # --------------------------------------------------------
    # 检测报告
    # --------------------------------------------------------

    report = {
        "generated_at":
            int(time.time()),

        "all_channels":
            len(all_channels),

        "target_channels":
            len(candidates),

        "tested":
            len(selected),

        "reachable":
            len(checked),

        "best":
            len(best_channels),

        "real_4k":
            len(cctv_4k),

        "channels":
            checked
    }

    (
        OUTPUT_DIR
        / "check_report.json"
    ).write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("")
    print(
        "=============================="
    )

    print(
        f"全部源：{len(all_channels)}"
    )

    print(
        f"目标源：{len(candidates)}"
    )

    print(
        f"实际检测：{len(selected)}"
    )

    print(
        f"可访问：{len(checked)}"
    )

    print(
        f"最终频道：{len(best_channels)}"
    )

    print(
        f"真正 4K：{len(cctv_4k)}"
    )

    print(
        "=============================="
    )


if __name__ == "__main__":
    main()
