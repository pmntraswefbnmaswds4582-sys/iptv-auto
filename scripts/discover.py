from urllib.request import Request, urlopen
from pathlib import Path
import re
import json
import time


# ============================================================
# 配置
# ============================================================

SOURCE_URL = (
    "https://iptv-org.github.io/iptv/index.m3u"
)

OUTPUT_DIR = Path("output")
RAW_FILE = OUTPUT_DIR / "discovered.json"

TIMEOUT = 20


# ============================================================
# 精确频道 ID
#
# 不再使用：
# Phoenix / Guangdong / Sports 等模糊关键词
#
# 只认 tvg-id
# ============================================================

EXACT_CHANNELS = {

    # --------------------------------------------------------
    # CCTV
    # --------------------------------------------------------

    "CCTV1.cn",
    "CCTV2.cn",
    "CCTV3.cn",
    "CCTV4.cn",
    "CCTV5.cn",
    "CCTV5Plus.cn",
    "CCTV6.cn",
    "CCTV7.cn",
    "CCTV8.cn",
    "CCTV9.cn",
    "CCTV10.cn",
    "CCTV11.cn",
    "CCTV12.cn",
    "CCTV13.cn",
    "CCTV14.cn",
    "CCTV15.cn",
    "CCTV16.cn",
    "CCTV17.cn",

    # CCTV 4K
    "CCTV4K.cn",

    # --------------------------------------------------------
    # 凤凰
    # --------------------------------------------------------

    "PhoenixChineseChannel.hk",
    "PhoenixInfoNewsChannel.hk",

    # --------------------------------------------------------
    # 广东
    # --------------------------------------------------------

    "GuangdongSports.cn",

    # 常见广东电视台频道
    "GuangdongTV.cn",
    "GuangdongNews.cn",
    "GuangdongZhujiang.cn",
    "GuangdongPearlRiver.cn",
    "GuangdongFilm.cn",
    "GuangdongPublic.cn",
    "GuangdongChildren.cn",
}


# ============================================================
# 港澳台
#
# 这里不通过频道名称判断。
#
# tvg-id 必须明确属于：
#
# .hk = 香港
# .mo = 澳门
# .tw = 台湾
#
# 因此不会把 Phoenix AZ 这种美国频道混进来。
# ============================================================

REGION_SUFFIXES = (
    ".hk",
    ".mo",
    ".tw",
)


# ============================================================
# 下载
# ============================================================

def download(url):

    print(f"[下载] {url}")

    request = Request(
        url,
        headers={
            "User-Agent": "iptv-auto/2.0"
        }
    )

    with urlopen(
        request,
        timeout=TIMEOUT
    ) as response:

        data = response.read()

    return data.decode(
        "utf-8",
        errors="ignore"
    )


# ============================================================
# 判断是否为目标频道
# ============================================================

def is_target_channel(tvg_id):

    if not tvg_id:
        return False

    tvg_id = tvg_id.strip()

    # 精确频道
    if tvg_id in EXACT_CHANNELS:
        return True

    # 港澳台：
    # 必须以明确地区后缀结尾
    if tvg_id.endswith(
        REGION_SUFFIXES
    ):
        return True

    return False


# ============================================================
# 分类
# ============================================================

def classify_channel(
    tvg_id,
    name
):

    tvg_id_lower = tvg_id.lower()

    name_lower = name.lower()

    # CCTV
    if tvg_id_lower.startswith(
        "cctv"
    ):

        if tvg_id_lower == "cctv4k.cn":
            return "央视4K"

        return "央视"

    # 凤凰
    if tvg_id in {
        "PhoenixChineseChannel.hk",
        "PhoenixInfoNewsChannel.hk",
    }:

        return "凤凰卫视"

    # 广东体育
    if tvg_id == "GuangdongSports.cn":

        return "广东体育"

    # 广东其他
    if tvg_id.startswith(
        "Guangdong"
    ):

        return "广东"

    # 香港
    if tvg_id.endswith(".hk"):

        return "香港"

    # 澳门
    if tvg_id.endswith(".mo"):

        return "澳门"

    # 台湾
    if tvg_id.endswith(".tw"):

        return "台湾"

    return "其他"


# ============================================================
# 解析 M3U
# ============================================================

def parse_m3u(text):

    lines = [
        x.strip()
        for x in text.splitlines()
        if x.strip()
    ]

    channels = []

    current_info = None

    for line in lines:

        # ----------------------------------------------------
        # EXTINF
        # ----------------------------------------------------

        if line.startswith(
            "#EXTINF"
        ):

            current_info = line

            continue

        # ----------------------------------------------------
        # URL
        # ----------------------------------------------------

        if (
            current_info
            and not line.startswith("#")
            and (
                line.startswith("http://")
                or line.startswith("https://")
            )
        ):

            # ------------------------------------------------
            # tvg-id
            # ------------------------------------------------

            tvg_id_match = re.search(
                r'tvg-id="([^"]*)"',
                current_info,
                re.IGNORECASE
            )

            if not tvg_id_match:

                current_info = None

                continue

            tvg_id = (
                tvg_id_match.group(1)
                .strip()
            )

            # ------------------------------------------------
            # 精确频道过滤
            # ------------------------------------------------

            if not is_target_channel(
                tvg_id
            ):

                current_info = None

                continue

            # ------------------------------------------------
            # 频道名称
            # ------------------------------------------------

            if "," in current_info:

                name = (
                    current_info
                    .split(",", 1)[1]
                    .strip()
                )

            else:

                name = tvg_id

            # ------------------------------------------------
            # group
            # ------------------------------------------------

            group_match = re.search(
                r'group-title="([^"]*)"',
                current_info,
                re.IGNORECASE
            )

            group = (
                group_match.group(1)
                if group_match
                else ""
            )

            # ------------------------------------------------
            # logo
            # ------------------------------------------------

            logo_match = re.search(
                r'tvg-logo="([^"]*)"',
                current_info,
                re.IGNORECASE
            )

            logo = (
                logo_match.group(1)
                if logo_match
                else ""
            )

            category = classify_channel(
                tvg_id,
                name
            )

            channels.append({

                "name": name,

                "tvg_id": tvg_id,

                "logo": logo,

                "group": group,

                "category": category,

                "url": line
            })

            current_info = None

    return channels


# ============================================================
# 去重
# ============================================================

def clean_channels(channels):

    result = []

    seen = set()

    for channel in channels:

        tvg_id = channel[
            "tvg_id"
        ]

        url = channel[
            "url"
        ]

        key = (
            tvg_id,
            url
        )

        if key in seen:
            continue

        seen.add(key)

        result.append(
            channel
        )

    return result


# ============================================================
# 主程序
# ============================================================

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    print(
        "=============================="
    )

    print(
        " IPTV 精确频道发现系统"
    )

    print(
        "=============================="
    )

    text = download(
        SOURCE_URL
    )

    print(
        "[解析] 开始解析 M3U"
    )

    channels = parse_m3u(
        text
    )

    print(
        f"[精确筛选] {len(channels)}"
    )

    channels = clean_channels(
        channels
    )

    print(
        f"[去重后] {len(channels)}"
    )

    # --------------------------------------------------------
    # 分类统计
    # --------------------------------------------------------

    statistics = {}

    for channel in channels:

        category = channel[
            "category"
        ]

        statistics[
            category
        ] = (
            statistics.get(
                category,
                0
            ) + 1
        )

    print(
        "------------------------------"
    )

    for category, count in sorted(
        statistics.items()
    ):

        print(
            f"{category}: {count}"
        )

    print(
        "------------------------------"
    )

    # --------------------------------------------------------
    # 输出
    # --------------------------------------------------------

    data = {

        "generated_at":
            int(time.time()),

        "source":
            SOURCE_URL,

        "channel_count":
            len(channels),

        "statistics":
            statistics,

        "channels":
            channels
    }

    RAW_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        f"[完成] {RAW_FILE}"
    )

    print(
        "=============================="
    )


if __name__ == "__main__":

    main()
