from urllib.request import Request, urlopen
from pathlib import Path
import json
import time
import re
import subprocess
import shutil


# ============================================================
# 配置
# ============================================================

INPUT_FILE = Path("output/discovered.json")
OUTPUT_FILE = Path("output/checked.json")

TIMEOUT = 15

# 每个直播源检测次数
CHECK_ROUNDS = 3

# 每次检测读取的数据量
READ_BYTES = 1024 * 256

# 两次检测之间等待时间
ROUND_DELAY = 1

# 真正判定 4K 所需的最低宽度
TRUE_4K_WIDTH = 3840

# 真正判定 4K 所需的最低高度
TRUE_4K_HEIGHT = 2160


# ============================================================
# HTTP 请求
# ============================================================

def open_stream(url):

    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/136.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Connection": "close",
        }
    )

    return urlopen(
        request,
        timeout=TIMEOUT
    )


# ============================================================
# 单次基础检测
# ============================================================

def basic_check(url):

    result = {

        "success": False,

        "status": None,

        "response_time": None,

        "content_type": "",

        "bytes_read": 0,

        "error": "",
    }

    start = time.time()

    try:

        response = open_stream(url)

        result["status"] = response.status

        result["content_type"] = (
            response.headers.get(
                "Content-Type",
                ""
            )
        )

        data = response.read(
            READ_BYTES
        )

        elapsed = time.time() - start

        result["response_time"] = round(
            elapsed,
            3
        )

        result["bytes_read"] = len(
            data
        )

        if (
            response.status >= 200
            and response.status < 400
            and len(data) > 0
        ):

            result["success"] = True

        response.close()

    except Exception as e:

        result["error"] = (
            f"{type(e).__name__}: {e}"
        )

        result["response_time"] = round(
            time.time() - start,
            3
        )

    return result


# ============================================================
# 多次稳定性检测
# ============================================================

def stability_check(url):

    rounds = []

    success_count = 0

    response_times = []

    total_bytes = 0

    for i in range(
        CHECK_ROUNDS
    ):

        print(
            f"      检测 {i + 1}/{CHECK_ROUNDS}"
        )

        result = basic_check(
            url
        )

        rounds.append(
            result
        )

        if result["success"]:

            success_count += 1

        if result["response_time"] is not None:

            response_times.append(
                result["response_time"]
            )

        total_bytes += (
            result["bytes_read"]
        )

        if i < CHECK_ROUNDS - 1:

            time.sleep(
                ROUND_DELAY
            )

    success_rate = (
        success_count
        / CHECK_ROUNDS
    )

    if response_times:

        avg_response = round(
            sum(response_times)
            / len(response_times),
            3
        )

    else:

        avg_response = None

    # --------------------------------------------------------
    # 稳定性评分
    # --------------------------------------------------------

    score = 0

    # 成功率最高 70 分
    score += (
        success_rate * 70
    )

    # 响应速度最高 20 分
    if avg_response is not None:

        if avg_response <= 1:

            score += 20

        elif avg_response <= 2:

            score += 16

        elif avg_response <= 4:

            score += 12

        elif avg_response <= 8:

            score += 6

        else:

            score += 2

    # 有实际数据最高 10 分
    if total_bytes > 0:

        score += 10

    score = round(
        score,
        2
    )

    return {

        "success_count":
            success_count,

        "total_rounds":
            CHECK_ROUNDS,

        "success_rate":
            round(
                success_rate,
                3
            ),

        "average_response_time":
            avg_response,

        "total_bytes":
            total_bytes,

        "score":
            score,

        "rounds":
            rounds,
    }


# ============================================================
# ffprobe 检测
#
# 如果 GitHub Actions 环境存在 ffprobe，
# 则尝试读取真实媒体流信息。
#
# 如果不存在，不让整个流程失败。
# ============================================================

def find_ffprobe():

    path = shutil.which(
        "ffprobe"
    )

    return path


# ============================================================
# 解析分辨率
# ============================================================

def parse_resolution(value):

    if not value:

        return None, None

    match = re.search(
        r"(\d{3,5})\s*[xX]\s*(\d{3,5})",
        value
    )

    if not match:

        return None, None

    width = int(
        match.group(1)
    )

    height = int(
        match.group(2)
    )

    return width, height


# ============================================================
# ffprobe 媒体检测
# ============================================================

def probe_media(
    url,
    ffprobe_path
):

    result = {

        "available":
            bool(ffprobe_path),

        "success":
            False,

        "width":
            None,

        "height":
            None,

        "codec":
            "",

        "bitrate":
            None,

        "fps":
            None,

        "is_4k":
            False,

        "error":
            "",
    }

    if not ffprobe_path:

        result["error"] = (
            "ffprobe not installed"
        )

        return result

    command = [

        ffprobe_path,

        "-v",
        "error",

        "-select_streams",
        "v:0",

        "-show_entries",
        (
            "stream="
            "width,"
            "height,"
            "codec_name,"
            "bit_rate,"
            "r_frame_rate"
        ),

        "-of",
        "json",

        "-timeout",
        "10000000",

        url,
    ]

    try:

        completed = subprocess.run(

            command,

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE,

            text=True,

            timeout=TIMEOUT + 10,
        )

        if completed.returncode != 0:

            result["error"] = (
                completed.stderr.strip()
            )

            return result

        data = json.loads(
            completed.stdout
        )

        streams = data.get(
            "streams",
            []
        )

        if not streams:

            result["error"] = (
                "no video stream"
            )

            return result

        stream = streams[0]

        width = stream.get(
            "width"
        )

        height = stream.get(
            "height"
        )

        result["width"] = width

        result["height"] = height

        result["codec"] = (
            stream.get(
                "codec_name"
            )
            or ""
        )

        bitrate = stream.get(
            "bit_rate"
        )

        if bitrate:

            try:

                result["bitrate"] = int(
                    bitrate
                )

            except Exception:

                pass

        fps = stream.get(
            "r_frame_rate"
        )

        result["fps"] = fps

        if (
            width
            and height
            and width >= TRUE_4K_WIDTH
            and height >= TRUE_4K_HEIGHT
        ):

            result["is_4k"] = True

        result["success"] = True

    except subprocess.TimeoutExpired:

        result["error"] = (
            "ffprobe timeout"
        )

    except Exception as e:

        result["error"] = (
            f"{type(e).__name__}: {e}"
        )

    return result


# ============================================================
# 综合评分
# ============================================================

def calculate_final_score(
    stability,
    media
):

    score = stability[
        "score"
    ]

    # --------------------------------------------------------
    # 真 4K 加分
    # --------------------------------------------------------

    if media.get(
        "is_4k",
        False
    ):

        score += 25

    # --------------------------------------------------------
    # 能读取真实视频流
    # --------------------------------------------------------

    if media.get(
        "success",
        False
    ):

        score += 5

    # --------------------------------------------------------
    # 最终封顶 100
    # --------------------------------------------------------

    return round(
        min(
            score,
            100
        ),
        2
    )


# ============================================================
# 检测单个频道源
# ============================================================

def check_channel(
    channel,
    ffprobe_path
):

    tvg_id = channel[
        "tvg_id"
    ]

    name = channel[
        "name"
    ]

    url = channel[
        "url"
    ]

    print(
        f"\n  [{tvg_id}] {name}"
    )

    print(
        f"      URL: {url}"
    )

    # --------------------------------------------------------
    # 稳定性
    # --------------------------------------------------------

    stability = stability_check(
        url
    )

    # --------------------------------------------------------
    # 如果完全不可用
    # --------------------------------------------------------

    if stability[
        "success_count"
    ] == 0:

        print(
            "      ❌ 三次检测全部失败"
        )

        return {

            **channel,

            "available":
                False,

            "stability":
                stability,

            "media":
                {

                    "available":
                        bool(ffprobe_path),

                    "success":
                        False,

                    "width":
                        None,

                    "height":
                        None,

                    "codec":
                        "",

                    "bitrate":
                        None,

                    "fps":
                        None,

                    "is_4k":
                        False,

                    "error":
                        "basic check failed",
                },

            "final_score":
                0,
        }

    print(
        f"      成功率: "
        f"{stability['success_rate'] * 100:.1f}%"
    )

    print(
        f"      平均响应: "
        f"{stability['average_response_time']} 秒"
    )

    print(
        f"      稳定性评分: "
        f"{stability['score']}"
    )

    # --------------------------------------------------------
    # 媒体检测
    # --------------------------------------------------------

    media = probe_media(
        url,
        ffprobe_path
    )

    if media[
        "success"
    ]:

        print(
            f"      分辨率: "
            f"{media['width']}x"
            f"{media['height']}"
        )

        print(
            f"      编码: "
            f"{media['codec']}"
        )

        if media[
            "is_4k"
        ]:

            print(
                "      ⭐ 真 4K"
            )

    else:

        print(
            "      媒体信息："
            "暂时无法确认"
        )

    final_score = calculate_final_score(
        stability,
        media
    )

    print(
        f"      最终评分: "
        f"{final_score}"
    )

    return {

        **channel,

        "available":
            True,

        "stability":
            stability,

        "media":
            media,

        "final_score":
            final_score,
    }


# ============================================================
# 按频道分组
# ============================================================

def group_channels(channels):

    groups = {}

    for channel in channels:

        tvg_id = channel[
            "tvg_id"
        ]

        groups.setdefault(
            tvg_id,
            []
        )

        groups[
            tvg_id
        ].append(
            channel
        )

    return groups


# ============================================================
# 选择最佳源
# ============================================================

def select_best_source(
    channels
):

    if not channels:

        return None

    # --------------------------------------------------------
    # 排序原则：
    #
    # 1. 可用
    # 2. 真 4K
    # 3. 最终评分
    # 4. 稳定成功率
    # 5. 响应速度
    # --------------------------------------------------------

    def sort_key(channel):

        media = channel.get(
            "media",
            {}
        )

        stability = channel.get(
            "stability",
            {}
        )

        response = stability.get(
            "average_response_time"
        )

        if response is None:

            response = 999999

        return (

            1
            if channel.get(
                "available",
                False
            )
            else 0,

            1
            if media.get(
                "is_4k",
                False
            )
            else 0,

            channel.get(
                "final_score",
                0
            ),

            stability.get(
                "success_rate",
                0
            ),

            -response,
        )

    return sorted(
        channels,
        key=sort_key,
        reverse=True
    )[0]


# ============================================================
# 主程序
# ============================================================

def main():

    print(
        "================================================"
    )

    print(
        " IPTV 直播源稳定性检测系统"
    )

    print(
        "================================================"
    )

    # --------------------------------------------------------
    # 检查输入
    # --------------------------------------------------------

    if not INPUT_FILE.exists():

        print(
            f"[错误] 找不到："
            f"{INPUT_FILE}"
        )

        print(
            "请先运行 discover.py"
        )

        return

    # --------------------------------------------------------
    # 读取 discovered.json
    # --------------------------------------------------------

    print(
        f"[读取] {INPUT_FILE}"
    )

    data = json.loads(
        INPUT_FILE.read_text(
            encoding="utf-8"
        )
    )

    channels = data.get(
        "channels",
        []
    )

    print(
        f"[发现] "
        f"{len(channels)} 个候选源"
    )

    if not channels:

        print(
            "[错误] 没有候选频道"
        )

        return

    # --------------------------------------------------------
    # ffprobe
    # --------------------------------------------------------

    ffprobe_path = find_ffprobe()

    if ffprobe_path:

        print(
            f"[媒体检测] "
            f"发现 ffprobe："
            f"{ffprobe_path}"
        )

    else:

        print(
            "[媒体检测] "
            "当前环境没有 ffprobe"
        )

        print(
            "后续 GitHub Actions 会安装"
        )

    # --------------------------------------------------------
    # 开始检测
    # --------------------------------------------------------

    checked_channels = []

    total = len(
        channels
    )

    for index, channel in enumerate(
        channels,
        start=1
    ):

        print(
            "\n------------------------------------------------"
        )

        print(
            f"[{index}/{total}]"
        )

        result = check_channel(
            channel,
            ffprobe_path
        )

        checked_channels.append(
            result
        )

    # --------------------------------------------------------
    # 按频道分组
    # --------------------------------------------------------

    groups = group_channels(
        checked_channels
    )

    best_channels = []

    for tvg_id, candidates in groups.items():

        best = select_best_source(
            candidates
        )

        if best:

            best_channels.append(
                best
            )

    # --------------------------------------------------------
    # 最佳源排序
    # --------------------------------------------------------

    best_channels.sort(

        key=lambda x: (
            x.get(
                "category",
                ""
            ),
            x.get(
                "name",
                ""
            ),
        )

    )

    # --------------------------------------------------------
    # 统计
    # --------------------------------------------------------

    available_count = sum(

        1
        for x in checked_channels
        if x.get(
            "available",
            False
        )

    )

    true_4k_count = sum(

        1
        for x in checked_channels
        if x.get(
            "media",
            {}
        ).get(
            "is_4k",
            False
        )

    )

    # --------------------------------------------------------
    # 输出
    # --------------------------------------------------------

    output = {

        "generated_at":
            int(time.time()),

        "source":
            data.get(
                "source",
                ""
            ),

        "input_channel_count":
            len(channels),

        "available_source_count":
            available_count,

        "true_4k_source_count":
            true_4k_count,

        "best_channel_count":
            len(best_channels),

        "check_rounds":
            CHECK_ROUNDS,

        "channels":
            checked_channels,

        "best_channels":
            best_channels,
    }

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUTPUT_FILE.write_text(

        json.dumps(
            output,
            ensure_ascii=False,
            indent=2
        ),

        encoding="utf-8"
    )

    # --------------------------------------------------------
    # 完成
    # --------------------------------------------------------

    print(
        "\n================================================"
    )

    print(
        " 检测完成"
    )

    print(
        "================================================"
    )

    print(
        f"候选源：{len(channels)}"
    )

    print(
        f"可用源：{available_count}"
    )

    print(
        f"检测到真 4K：{true_4k_count}"
    )

    print(
        f"频道最佳源：{len(best_channels)}"
    )

    print(
        f"输出：{OUTPUT_FILE}"
    )

    print(
        "================================================"
    )


if __name__ == "__main__":

    main()
