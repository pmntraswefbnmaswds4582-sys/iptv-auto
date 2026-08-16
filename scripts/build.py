from pathlib import Path
import json
import time


# ============================================================
# IPTV 最佳源生成器
#
# 输入：
#   output/checked.json
#
# 输出：
#   output/best.m3u
#
# 规则：
#   1. 只使用 check.py 已经判定 available=true 的源
#   2. 只使用每个频道筛选出的最佳源
#   3. 不重新判断直播源
#   4. 不修改 URL
#   5. 保留 tvg-id / logo / group-title
# ============================================================


INPUT_FILE = Path(
    "output/checked.json"
)

OUTPUT_FILE = Path(
    "output/best.m3u"
)


# ============================================================
# 分类排序
# ============================================================

CATEGORY_ORDER = {

    "央视4K": 1,

    "央视": 2,

    "凤凰卫视": 3,

    "广东体育": 4,

    "广东": 5,

    "香港": 6,

    "澳门": 7,

    "台湾": 8,

    "其他": 9,

}


# ============================================================
# M3U 文本安全处理
# ============================================================

def clean_text(value):

    if value is None:

        return ""

    value = str(
        value
    )

    value = value.replace(
        "\r",
        " "
    )

    value = value.replace(
        "\n",
        " "
    )

    return value.strip()


# ============================================================
# 生成 EXTINF
# ============================================================

def build_extinf(
    channel
):

    name = clean_text(
        channel.get(
            "name",
            ""
        )
    )


    tvg_id = clean_text(
        channel.get(
            "tvg_id",
            ""
        )
    )


    logo = clean_text(
        channel.get(
            "logo",
            ""
        )
    )


    category = clean_text(
        channel.get(
            "category",
            ""
        )
    )


    # --------------------------------------------------------
    # 如果 category 为空
    # 使用 group
    # --------------------------------------------------------

    if not category:

        category = clean_text(
            channel.get(
                "group",
                ""
            )
        )


    # --------------------------------------------------------
    # 最终兜底
    # --------------------------------------------------------

    if not category:

        category = "其他"


    # --------------------------------------------------------
    # EXTINF
    # --------------------------------------------------------

    parts = [

        "#EXTINF:-1",

        f'tvg-id="{tvg_id}"',

    ]


    if logo:

        parts.append(
            f'tvg-logo="{logo}"'
        )


    parts.append(
        f'group-title="{category}"'
    )


    extinf = (
        " ".join(parts)
        + ","
        + name
    )


    return extinf


# ============================================================
# 排序
# ============================================================

def sort_channels(
    channels
):

    def sort_key(
        channel
    ):

        category = (
            channel.get(
                "category",
                "其他"
            )
        )


        category_order = (
            CATEGORY_ORDER.get(
                category,
                99
            )
        )


        tvg_id = (
            channel.get(
                "tvg_id",
                ""
            )
        )


        name = (
            channel.get(
                "name",
                ""
            )
        )


        # ----------------------------------------------------
        # 4K 优先
        #
        # 但只有 check.py 明确判定
        # is_true_4k=true 才算。
        # ----------------------------------------------------

        true_4k = (

            0

            if channel.get(
                "is_true_4k",
                False
            )

            else 1

        )


        # ----------------------------------------------------
        # 真实分辨率
        # ----------------------------------------------------

        width = int(
            channel.get(
                "width",
                0
            )
            or 0
        )


        height = int(
            channel.get(
                "height",
                0
            )
            or 0
        )


        pixels = (
            width
            * height
        )


        return (

            category_order,

            true_4k,

            -pixels,

            tvg_id,

            name,

        )


    return sorted(
        channels,
        key=sort_key
    )


# ============================================================
# 主程序
# ============================================================

def main():

    print(
        "================================================"
    )

    print(
        " IPTV 最佳源生成系统"
    )

    print(
        "================================================"
    )


    # ========================================================
    # 检查输入
    # ========================================================

    print(
        f"[读取] {INPUT_FILE}"
    )


    if not INPUT_FILE.exists():

        print(
            "[错误] "
            f"{INPUT_FILE} 不存在"
        )

        raise SystemExit(
            1
        )


    # ========================================================
    # 读取 JSON
    # ========================================================

    try:

        data = json.loads(

            INPUT_FILE.read_text(
                encoding="utf-8"
            )

        )

    except Exception as e:

        print(
            "[错误] "
            "无法读取 checked.json"
        )

        print(
            str(e)
        )

        raise SystemExit(
            1
        )


    # ========================================================
    # 获取最佳频道
    # ========================================================

    channels = data.get(
        "channels",
        []
    )


    print(
        f"[读取完成] "
        f"{len(channels)} 个最佳频道"
    )


    if not channels:

        print(
            "[错误] "
            "checked.json 中没有最佳频道"
        )

        raise SystemExit(
            1
        )


    # ========================================================
    # 严格过滤
    # ========================================================

    valid_channels = []


    seen_ids = set()


    for channel in channels:

        # ----------------------------------------------------
        # 必须 available
        # ----------------------------------------------------

        if not channel.get(
            "available",
            False
        ):

            continue


        # ----------------------------------------------------
        # URL 必须存在
        # ----------------------------------------------------

        url = clean_text(
            channel.get(
                "url",
                ""
            )
        )


        if not url:

            continue


        # ----------------------------------------------------
        # tvg-id 必须存在
        # ----------------------------------------------------

        tvg_id = clean_text(
            channel.get(
                "tvg_id",
                ""
            )
        )


        if not tvg_id:

            continue


        # ----------------------------------------------------
        # 每个 tvg-id 只允许一个最佳源
        # ----------------------------------------------------

        if tvg_id in seen_ids:

            continue


        seen_ids.add(
            tvg_id
        )


        valid_channels.append(
            channel
        )


    print(
        f"[有效频道] "
        f"{len(valid_channels)}"
    )


    if not valid_channels:

        print(
            "[错误] "
            "没有可以生成 M3U 的频道"
        )

        raise SystemExit(
            1
        )


    # ========================================================
    # 排序
    # ========================================================

    valid_channels = sort_channels(
        valid_channels
    )


    # ========================================================
    # M3U
    # ========================================================

    lines = [

        "#EXTM3U",

    ]


    for channel in valid_channels:

        extinf = build_extinf(
            channel
        )


        url = clean_text(
            channel.get(
                "url",
                ""
            )
        )


        lines.append(
            extinf
        )


        lines.append(
            url
        )


    # ========================================================
    # 写文件
    # ========================================================

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )


    OUTPUT_FILE.write_text(

        "\n".join(
            lines
        )
        + "\n",

        encoding="utf-8"

    )


    # ========================================================
    # 分类统计
    # ========================================================

    statistics = {}


    for channel in valid_channels:

        category = (
            channel.get(
                "category",
                "其他"
            )
        )


        statistics[
            category
        ] = (

            statistics.get(
                category,
                0
            )

            + 1

        )


    # ========================================================
    # 输出统计
    # ========================================================

    print(
        "----------------------------------------"
    )


    print(
        "[最终频道]"
    )


    for category, count in sorted(

        statistics.items(),

        key=lambda item:
            CATEGORY_ORDER.get(
                item[0],
                99
            )

    ):

        print(
            f"  {category}: "
            f"{count}"
        )


    print(
        "----------------------------------------"
    )


    # ========================================================
    # 真 4K
    # ========================================================

    true_4k_count = sum(

        1

        for channel in valid_channels

        if channel.get(
            "is_true_4k",
            False
        )

    )


    print(
        f"[真 4K] "
        f"{true_4k_count}"
    )


    # ========================================================
    # 输出文件
    # ========================================================

    print(
        f"[完成] "
        f"{OUTPUT_FILE}"
    )


    print(
        f"[频道数量] "
        f"{len(valid_channels)}"
    )


    print(
        "================================================"
    )


if __name__ == "__main__":

    main()
