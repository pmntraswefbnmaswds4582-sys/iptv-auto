from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from pathlib import Path
import subprocess
import json
import time
import re


# ============================================================
# IPTV 直播源稳定性检测系统 v4
#
# 功能：
#
# 1. 读取 discover.py 产生的 discovered.json
# 2. 每个直播源进行 3 次稳定性检测
# 3. 使用 ffprobe 尝试确认真实媒体信息
# 4. 严格区分：
#       720p
#       1080p
#       4K
#       未确认
# 5. 真 4K 必须实际检测到 >= 3840x2160
# 6. 每个频道自动选择最佳源
# 7. 输出 output/checked.json
#
# 注意：
# EXTINF 中的 (1080p)/(4K) 只作为参考，
# 不作为真实画质判定依据。
# ============================================================


# ============================================================
# 配置
# ============================================================

INPUT_FILE = Path(
    "output/discovered.json"
)

OUTPUT_FILE = Path(
    "output/checked.json"
)

TEST_COUNT = 3

# 单次 HTTP 请求最大等待时间
HTTP_TIMEOUT = 8

# ffprobe 最大等待时间
FFPROBE_TIMEOUT = 10

# 每次检测之间稍微间隔
TEST_INTERVAL = 0.5


# ============================================================
# HTTP 请求
# ============================================================

def http_test(url):

    start_time = time.perf_counter()

    try:

        request = Request(
            url,
            headers={
                "User-Agent":
                    "Mozilla/5.0 "
                    "(compatible; IPTV-Auto/4.0)"
            }
        )

        with urlopen(
            request,
            timeout=HTTP_TIMEOUT
        ) as response:

            # ------------------------------------------------
            # 不下载整个直播流。
            #
            # 只读取少量数据确认服务器能够正常响应。
            # ------------------------------------------------

            response.read(1024)

            elapsed = (
                time.perf_counter()
                - start_time
            )

            status = getattr(
                response,
                "status",
                200
            )

            if status >= 400:

                return {
                    "success": False,
                    "response_time": elapsed,
                    "error":
                        f"HTTP {status}"
                }

            return {
                "success": True,
                "response_time": elapsed,
                "error": ""
            }


    except HTTPError as e:

        elapsed = (
            time.perf_counter()
            - start_time
        )

        return {
            "success": False,
            "response_time": elapsed,
            "error":
                f"HTTP {e.code}"
        }


    except (
        URLError,
        TimeoutError,
        OSError,
        Exception
    ) as e:

        elapsed = (
            time.perf_counter()
            - start_time
        )

        return {
            "success": False,
            "response_time": elapsed,
            "error":
                str(e)
        }


# ============================================================
# 查找 ffprobe
# ============================================================

def find_ffprobe():

    possible_paths = [

        "/usr/bin/ffprobe",

        "/usr/local/bin/ffprobe",

        "ffprobe",

    ]

    for path in possible_paths:

        try:

            result = subprocess.run(

                [
                    path,
                    "-version"
                ],

                stdout=subprocess.DEVNULL,

                stderr=subprocess.DEVNULL,

                timeout=5

            )

            if result.returncode == 0:

                return path

        except Exception:

            continue

    return None


# ============================================================
# ffprobe 媒体检测
# ============================================================

def probe_media(
    ffprobe_path,
    url
):

    if not ffprobe_path:

        return {
            "confirmed": False,
            "width": 0,
            "height": 0,
            "codec": "",
            "fps": 0,
            "error":
                "ffprobe unavailable"
        }


    command = [

        ffprobe_path,

        "-v",
        "error",

        "-timeout",
        "5000000",

        "-user_agent",
        "Mozilla/5.0",

        "-rw_timeout",
        "5000000",

        "-select_streams",
        "v:0",

        "-show_entries",
        "stream=width,height,codec_name,r_frame_rate",

        "-of",
        "json",

        url

    ]


    try:

        result = subprocess.run(

            command,

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE,

            text=True,

            timeout=FFPROBE_TIMEOUT

        )


        if result.returncode != 0:

            return {
                "confirmed": False,
                "width": 0,
                "height": 0,
                "codec": "",
                "fps": 0,
                "error":
                    result.stderr.strip()
            }


        data = json.loads(
            result.stdout
        )


        streams = data.get(
            "streams",
            []
        )


        if not streams:

            return {
                "confirmed": False,
                "width": 0,
                "height": 0,
                "codec": "",
                "fps": 0,
                "error":
                    "no video stream"
            }


        stream = streams[0]


        width = int(
            stream.get(
                "width",
                0
            ) or 0
        )

        height = int(
            stream.get(
                "height",
                0
            ) or 0
        )

        codec = (
            stream.get(
                "codec_name",
                ""
            )
            or ""
        )


        # ----------------------------------------------------
        # FPS
        # ----------------------------------------------------

        fps = 0.0

        fps_string = (
            stream.get(
                "r_frame_rate",
                ""
            )
            or ""
        )


        if "/" in fps_string:

            try:

                numerator, denominator = (
                    fps_string.split(
                        "/",
                        1
                    )
                )

                numerator = float(
                    numerator
                )

                denominator = float(
                    denominator
                )

                if denominator != 0:

                    fps = (
                        numerator
                        / denominator
                    )

            except Exception:

                fps = 0.0


        return {

            "confirmed":
                width > 0
                and height > 0,

            "width":
                width,

            "height":
                height,

            "codec":
                codec,

            "fps":
                round(
                    fps,
                    2
                ),

            "error":
                ""

        }


    except subprocess.TimeoutExpired:

        return {
            "confirmed": False,
            "width": 0,
            "height": 0,
            "codec": "",
            "fps": 0,
            "error":
                "ffprobe timeout"
        }


    except Exception as e:

        return {
            "confirmed": False,
            "width": 0,
            "height": 0,
            "codec": "",
            "fps": 0,
            "error":
                str(e)
        }


# ============================================================
# 画质分类
# ============================================================

def classify_resolution(
    width,
    height
):

    if width <= 0 or height <= 0:

        return "未确认"


    # --------------------------------------------------------
    # 真 4K
    #
    # 必须至少达到：
    #
    # 3840 x 2160
    # --------------------------------------------------------

    if (
        width >= 3840
        and height >= 2160
    ):

        return "4K"


    # --------------------------------------------------------
    # 1080p
    # --------------------------------------------------------

    if (
        width >= 1920
        and height >= 1080
    ):

        return "1080p"


    # --------------------------------------------------------
    # 720p
    # --------------------------------------------------------

    if (
        width >= 1280
        and height >= 720
    ):

        return "720p"


    # --------------------------------------------------------
    # 576p / SD
    # --------------------------------------------------------

    if (
        width >= 720
        and height >= 576
    ):

        return "576p/SD"


    return "低清"


# ============================================================
# 画质基础分
# ============================================================

def resolution_score(
    resolution
):

    scores = {

        "4K": 40,

        "1080p": 30,

        "720p": 20,

        "576p/SD": 10,

        "低清": 5,

        "未确认": 0,

    }

    return scores.get(
        resolution,
        0
    )


# ============================================================
# 稳定性评分
# ============================================================

def stability_score(
    success_rate,
    average_response
):

    # --------------------------------------------------------
    # 成功率基础分
    # --------------------------------------------------------

    score = (
        success_rate
        * 0.75
    )


    # --------------------------------------------------------
    # 响应速度
    #
    # 越快分数越高
    # --------------------------------------------------------

    if average_response <= 0.2:

        speed_score = 25

    elif average_response <= 0.5:

        speed_score = 22

    elif average_response <= 1:

        speed_score = 18

    elif average_response <= 2:

        speed_score = 12

    elif average_response <= 4:

        speed_score = 6

    else:

        speed_score = 0


    score += speed_score


    return round(
        score,
        1
    )


# ============================================================
# 最终评分
#
# 最高 100
#
# 稳定性：75
# 画质：25
#
# 注意：
# 未确认画质不会获得画质加分。
# ============================================================

def final_score(
    stability,
    resolution
):

    quality_points = {

        "4K": 25,

        "1080p": 20,

        "720p": 12,

        "576p/SD": 6,

        "低清": 2,

        "未确认": 0,

    }


    score = (
        stability
        + quality_points.get(
            resolution,
            0
        )
    )


    return round(
        min(
            score,
            100
        ),
        1
    )


# ============================================================
# 从名称中提取参考画质
#
# 仅保存。
#
# 绝不用于真实画质判定。
# ============================================================

def detect_declared_resolution(
    name
):

    if not name:

        return ""


    text = name.lower()


    if re.search(
        r"\b4k\b",
        text
    ):

        return "4K"


    if re.search(
        r"1080",
        text
    ):

        return "1080p"


    if re.search(
        r"720",
        text
    ):

        return "720p"


    if re.search(
        r"576",
        text
    ):

        return "576p"


    return ""


# ============================================================
# 检测单个频道
# ============================================================

def check_channel(
    channel,
    ffprobe_path
):

    url = channel.get(
        "url",
        ""
    )


    name = channel.get(
        "name",
        ""
    )


    tvg_id = channel.get(
        "tvg_id",
        ""
    )


    print(
        f"\n"
        f"  [{tvg_id}] "
        f"{name}"
    )


    print(
        f"      URL: {url}"
    )


    results = []


    # ========================================================
    # 三次稳定性检测
    # ========================================================

    for i in range(
        TEST_COUNT
    ):

        print(
            f"      检测 "
            f"{i + 1}/{TEST_COUNT}"
        )


        result = http_test(
            url
        )


        results.append(
            result
        )


        if i < TEST_COUNT - 1:

            time.sleep(
                TEST_INTERVAL
            )


    successful = [

        r

        for r in results

        if r["success"]

    ]


    success_count = len(
        successful
    )


    success_rate = (
        success_count
        / TEST_COUNT
        * 100
    )


    if successful:

        average_response = (

            sum(
                r["response_time"]
                for r
                in successful
            )

            / len(successful)

        )

    else:

        average_response = 0


    # ========================================================
    # 全部失败
    # ========================================================

    if not successful:

        print(
            "      ❌ "
            "三次检测全部失败"
        )


        return {

            **channel,

            "available":
                False,

            "success_count":
                0,

            "test_count":
                TEST_COUNT,

            "success_rate":
                0,

            "average_response":
                0,

            "stability_score":
                0,

            "media_confirmed":
                False,

            "width":
                0,

            "height":
                0,

            "resolution":
                "不可用",

            "codec":
                "",

            "fps":
                0,

            "declared_resolution":
                detect_declared_resolution(
                    name
                ),

            "is_true_4k":
                False,

            "final_score":
                0,

        }


    # ========================================================
    # 稳定性
    # ========================================================

    stability = stability_score(

        success_rate,

        average_response

    )


    print(
        f"      成功率: "
        f"{success_rate:.1f}%"
    )


    print(
        f"      平均响应: "
        f"{average_response:.3f} 秒"
    )


    print(
        f"      稳定性评分: "
        f"{stability}"
    )


    # ========================================================
    # 媒体检测
    # ========================================================

    media = probe_media(

        ffprobe_path,

        url

    )


    if media["confirmed"]:

        width = media[
            "width"
        ]

        height = media[
            "height"
        ]

        codec = media[
            "codec"
        ]

        fps = media[
            "fps"
        ]


        resolution = (
            classify_resolution(
                width,
                height
            )
        )


        print(
            f"      分辨率: "
            f"{width}x{height}"
        )


        print(
            f"      画质判定: "
            f"{resolution}"
        )


        if codec:

            print(
                f"      编码: "
                f"{codec}"
            )


        if fps:

            print(
                f"      帧率: "
                f"{fps} fps"
            )


    else:

        width = 0

        height = 0

        codec = ""

        fps = 0

        resolution = "未确认"


        print(
            "      媒体信息："
            "无法确认"
        )


    # ========================================================
    # 真 4K
    # ========================================================

    is_true_4k = (

        media["confirmed"]

        and width >= 3840

        and height >= 2160

    )


    # ========================================================
    # 最终评分
    # ========================================================

    score = final_score(

        stability,

        resolution

    )


    print(
        f"      最终评分: "
        f"{score}"
    )


    return {

        **channel,

        "available":
            True,

        "success_count":
            success_count,

        "test_count":
            TEST_COUNT,

        "success_rate":
            round(
                success_rate,
                1
            ),

        "average_response":
            round(
                average_response,
                3
            ),

        "stability_score":
            stability,

        "media_confirmed":
            media["confirmed"],

        "width":
            width,

        "height":
            height,

        "resolution":
            resolution,

        "codec":
            codec,

        "fps":
            fps,

        "declared_resolution":
            detect_declared_resolution(
                name
            ),

        "is_true_4k":
            is_true_4k,

        "final_score":
            score,

    }


# ============================================================
# 每频道选择最佳源
# ============================================================

def choose_best_channels(
    results
):

    groups = {}


    for item in results:

        if not item.get(
            "available",
            False
        ):

            continue


        channel_id = item.get(
            "channel_id",
            ""
        )


        if not channel_id:

            channel_id = item.get(
                "tvg_id",
                ""
            )


        groups.setdefault(
            channel_id,
            []
        ).append(
            item
        )


    best = []


    for channel_id, items in groups.items():

        # ----------------------------------------------------
        # 排序规则
        #
        # 1. 最终评分
        # 2. 真 4K
        # 3. 真实分辨率
        # 4. 稳定性
        # 5. 响应速度
        # ----------------------------------------------------

        items.sort(

            key=lambda x: (

                x.get(
                    "final_score",
                    0
                ),

                1
                if x.get(
                    "is_true_4k",
                    False
                )
                else 0,

                x.get(
                    "width",
                    0
                )
                * x.get(
                    "height",
                    0
                ),

                x.get(
                    "stability_score",
                    0
                ),

                -x.get(
                    "average_response",
                    999
                ),

            ),

            reverse=True

        )


        best.append(
            items[0]
        )


    # --------------------------------------------------------
    # 按频道 ID 排序
    # --------------------------------------------------------

    best.sort(

        key=lambda x:
            x.get(
                "channel_id",
                ""
            )

    )


    return best


# ============================================================
# 主程序
# ============================================================

def main():

    print(
        "================================================"
    )

    print(
        " IPTV 直播源稳定性检测系统 v4"
    )

    print(
        "================================================"
    )


    # ========================================================
    # 读取
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
            "[错误] "
            "没有候选频道"
        )

        raise SystemExit(
            1
        )


    # ========================================================
    # ffprobe
    # ========================================================

    ffprobe_path = (
        find_ffprobe()
    )


    if ffprobe_path:

        print(
            f"[媒体检测] "
            f"发现 ffprobe："
            f"{ffprobe_path}"
        )

    else:

        print(
            "[媒体检测] "
            "未发现 ffprobe"
        )


    # ========================================================
    # 开始检测
    # ========================================================

    results = []


    for index, channel in enumerate(
        channels,
        start=1
    ):

        print(
            "\n"
            "------------------------------------------------"
        )


        print(
            f"[{index}/{len(channels)}]"
        )


        result = check_channel(

            channel,

            ffprobe_path

        )


        results.append(
            result
        )


    # ========================================================
    # 可用源
    # ========================================================

    available = [

        item

        for item in results

        if item.get(
            "available",
            False
        )

    ]


    # ========================================================
    # 真 4K
    # ========================================================

    true_4k = [

        item

        for item in available

        if item.get(
            "is_true_4k",
            False
        )

    ]


    # ========================================================
    # 每频道最佳源
    # ========================================================

    best_channels = (
        choose_best_channels(
            results
        )
    )


    # ========================================================
    # 输出
    # ========================================================

    output = {

        "generated_at":
            int(time.time()),

        "source":
            data.get(
                "source",
                ""
            ),

        "candidate_count":
            len(channels),

        "available_count":
            len(available),

        "true_4k_count":
            len(true_4k),

        "best_channel_count":
            len(best_channels),

        "channels":
            best_channels,

        "all_results":
            results,

    }


    OUTPUT_FILE.write_text(

        json.dumps(

            output,

            ensure_ascii=False,

            indent=2

        ),

        encoding="utf-8"

    )


    # ========================================================
    # 最终统计
    # ========================================================

    print(
        "\n"
        "================================================"
    )

    print(
        " 检测完成"
    )

    print(
        "================================================"
    )


    print(
        f"候选源："
        f"{len(channels)}"
    )


    print(
        f"可用源："
        f"{len(available)}"
    )


    print(
        f"检测到真 4K："
        f"{len(true_4k)}"
    )


    print(
        f"频道最佳源："
        f"{len(best_channels)}"
    )


    print(
        f"输出："
        f"{OUTPUT_FILE}"
    )


    print(
        "================================================"
    )


if __name__ == "__main__":

    main()
