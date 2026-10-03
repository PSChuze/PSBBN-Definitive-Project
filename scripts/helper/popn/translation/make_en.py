#!/usr/bin/env python3
"""Generate elf.en.tsv from elf.tsv for pop'n Puzzle-dama Online.

A deterministic JP->EN map (plus regexes for the numbered mission objectives) so
every duplicate renders identically. Run from the popn/ dir:
    PYTHONUTF8=1 python translation/make_en.py
Then lint + build with pntext.py.
"""
import os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pntext

HERE = os.path.dirname(__file__)
SRC = os.path.join(HERE, "elf.tsv")
OUT = os.path.join(HERE, "elf.en.tsv")

# ---- exact-match map (JP -> EN) ---------------------------------------------
M = {
    # quick-chat phrases
    "よろしくお願いします。": "Thanks for the game!",
    "ルームを作ります。": "I'll make a room.",
    "ちょっと席を離れます。": "Away for a bit.",
    "そろそろやめます。": "I'll stop soon.",
    "ありがとうございました。": "Thank you!",
    # profile / occupation
    "家事手伝い": "Homemaker",
    "フリーター": "Part-timer",
    "その他": "Other",
    # chat system (name fragments: "<name>" + "さんが、" + "入室しました。")
    "入室しました。": "has entered.",
    "退室しました。": "has left.",
    "さんが、": " ",
    "さん": " ",
    "ようこそ！": "Welcome!",
    # generic error / prompt
    "エラーなし": "No error",
    "エラーなし。": "No error.",
    "エラー！": "Error!",
    "エラーコード  %d": "Error code  %d",
    "エラーコード %d": "Error code %d",
    "○ボタンを押してください。": "Press the ○ button.",
    "○ボタンを押してね！": "Press the ○ button!",
    # version / router
    "ご利用のルータが正しく設定されていない": "Your router may not be set up",
    "可能性があります。TCPポートの5730が": "correctly. Check that TCP port",
    "許可されているかご確認ください。": "5730 is allowed through.",
    "対戦相手のヴァージョンが古いです。": "Your opponent's version is old.",
    "あなたのヴァージョンが古いです。": "Your game version is old.",
    "対戦が開始できませんでした。": "The match could not start.",
    # network error table
    "ネットワーク設定ファイルのロードに失敗！": "Failed to load network settings!",
    "プロトコルエラー！": "Protocol error!",
    "データベースエラー！": "Database error!",
    "DNSサーバーエラー！": "DNS server error!",
    "ソケットエラー！": "Socket error!",
    "サーバーとの接続に失敗！": "Couldn't connect to the server!",
    "通信がタイムアウトしました！": "The connection timed out!",
    "IDが無効だよ！": "Invalid ID!",
    "IDにNGワードが含まれているよ！": "That ID has a banned word!",
    "別のIDで登録してね！": "Register with another ID!",
    "指定したIDはもう使われているよ！": "That ID is already taken!",
    "ユーザー名にNGワードが含まれているよ！": "That name has a banned word in it!",
    "別のユーザー名で登録してね！": "Register with another name!",
    "指定したユーザーはもう使われているよ！": "That username is already taken!",
    "ユーザー名が存在しないよ！": "That username doesn't exist!",
    "指定したIDが存在しないよ！": "That ID doesn't exist!",
    "IDかパスワードが間違っているよ！": "Wrong ID or password!",
    "もう一度入力してね！": "Please enter it again!",
    "登録が無効になっているよ！": "Your registration is inactive!",
    "すでにログインしているので": "You are already logged in,",
    "今はログインできないよ！": "so you can't log in now!",
    "ルームが存在しないよ！": "That room doesn't exist!",
    "エリアが存在しないよ！": "That area doesn't exist!",
    "エリアが満員だよ！": "The area is full!",
    "ルームが満員だよ！": "The room is full!",
    "ロビーサーバの認証に失敗したよ！": "Lobby server authentication failed!",
    "ロビーサーバの準備ができていないよ！": "The lobby server isn't ready yet!",
    "そのユーザーはいないよ！": "That user isn't here!",
    "ユーザーが見つからないよ！": "User not found!",
    "ルーム名にNGワードが含まれているよ！": "That room name has a banned word!",
    "別のルーム名で登録してね！": "Use another room name!",
    "ルーム数がいっぱいで作成できないよ！": "Too many rooms - can't make one!",
    "ユーザー名がないよ！": "No username!",
    "ルームのパスワードが違うよ！": "Wrong room password!",
    "ユーザーがエリアにすでにいるよ！": "That user is already in the area!",
    "ユーザーがルームにすでにいるよ！": "That user is already in the room!",
    "ルーム作成者ではないよ！": "You aren't the room's creator!",
    "対戦中だよ！": "In a match!",
    "初心者卒業おめでとう！": "You're a beginner no more!",
    "サーバーとの接続が切れているよ！": "Connection to the server was lost!",
    # DNAS / download / unique-id error codes ("DNAS" kept verbatim)
    '"DNAS"エラー (-101)': '"DNAS" error (-101)',
    '"DNAS"エラー (-102)': '"DNAS" error (-102)',
    '"DNAS"エラー (-103)': '"DNAS" error (-103)',
    '"DNAS"エラー (-104)': '"DNAS" error (-104)',
    '"DNAS"エラー (-105)': '"DNAS" error (-105)',
    '"DNAS"エラー (-106)': '"DNAS" error (-106)',
    '"DNAS"エラー (-107)': '"DNAS" error (-107)',
    '"DNAS"エラー (-108)': '"DNAS" error (-108)',
    '"DNAS"エラー (-401)': '"DNAS" error (-401)',
    '"DNAS"エラー (-402)': '"DNAS" error (-402)',
    '"DNAS"エラー (-403)': '"DNAS" error (-403)',
    '"DNAS"エラー (-404)': '"DNAS" error (-404)',
    '"DNAS"エラー (%d)': '"DNAS" error (%d)',
    "現在\"DNAS\"サーバーが処理を受け付けることが": "The \"DNAS\" server is not accepting",
    "できません。": "requests now.",
    "しばらく時間をおいてから再接続して下さい。": "Please wait a while, then reconnect.",
    "タイトルの\"DNAS\"認証サービス期間以前です。": "This title's \"DNAS\" service hasn't begun.",
    "タイトルの\"DNAS\"認証サービス期間が終了しま": "This title's \"DNAS\" service has ended.",
    "した。": " ",
    "全ての\"DNAS\"サービスが終了しました。": "All \"DNAS\" services have ended.",
    "\"DNAS\"サーバーとの接続がタイムアウトしまし": "The \"DNAS\" server connection timed out.",
    "た。": " ",
    "サーバーが正常に動作しておりません。": "The server is not working properly.",
    "\"DNAS\"エラーがおこりました。": "A \"DNAS\" error occurred.",
    "\"DNAS\"サーバーエラーです。": "\"DNAS\" server error.",
    "ユニークIDエラー (-701)": "Unique ID error (-701)",
    "ユニークIDエラーです。": "Unique ID error.",
    "ユニークIDエラー (-703)": "Unique ID error (-703)",
    "ダウンロードエラー (-201)": "Download error (-201)",
    "ダウンロードエラーです。": "Download error.",
    "ダウンロードエラー (-202)": "Download error (-202)",
    "ダウンロードエラー (-203)": "Download error (-203)",
    "ダウンロードエラー (-204)": "Download error (-204)",
    "機器情報エラーです。": "Device info error.",
    # connection / proxy / dns
    "ネットワーク接続を中断しました。": "The network connection was cut off.",
    "プロキシの設定にエラーがあります。": "There is an error in the proxy setup.",
    "通信がタイムアウトしました。": "The connection timed out.",
    "しばらく時間をおいてから再接続してくださ": "Please wait a while, then reconnect.",
    "い。": " ",
    "\"DNAS\"サーバーへの接続に失敗しました。": "Could not connect to the \"DNAS\" server.",
    "DNSサーバーの応答にエラーがあります。": "There is an error in the DNS response.",
    "ネットワーク設定を確認してください。": "Please check your network settings.",
    "DNSサーバーからの応答がありません。": "No response from the DNS server.",
    "DNSエラーです。": "DNS error.",
    "通信エラーです。": "Connection error.",
    # PlayStation BB Unit block (product names verbatim)
    "\"PlayStation BB Unit\"が\"PlayStation 2\"本体に": "The \"PlayStation BB Unit\" is not",
    "正しく接続されていません。": "connected to \"PlayStation 2\".",
    "ネットワーク設定に問題があります。": "There is a problem with the network setup.",
    "改めて\"PlayStation BB Unit\"の": "Set up \"PlayStation BB Unit\"",
    "ネットワーク設定を行って下さい。": "network settings again.",
    "\"PlayStation BB Unit\"が別の": "\"PlayStation BB Unit\" may be",
    "\"PlayStation2\"に接続された可能性があります。": "connected to another \"PlayStation2\".",
    "接続に失敗しました。": "Connection failed.",
    "\"PlayStation BB Unit\"の接続方法に": "How the \"PlayStation BB Unit\" is",
    "問題がある可能性があります。": "connected may be the problem.",
    "改めて\"PlayStation BB Unit\"の接続、": "Check the \"PlayStation BB Unit\"",
    "及びネットワーク設定を確認して下さい。": "connection and network settings.",
    "切断に失敗しました。": "Disconnect failed.",
    # in-game control hints
    "○×でたま変更": "○/×: Change ball",
    "L1 L2を押しながらで倍速変更": "Hold L1/L2 for 2x speed",
    "R1 R2で手玉、配置玉切り替え": "R1/R2: Swap hand/field ball",
    "SELECTと△□で問題変更": "SELECT+△□: Puzzle",
    "スタートで開始": "Press START",
    "△□で攻撃だま内容変更": "△□: Attack balls",
    "最大同時消し数 %d": "Max cleared at once: %d",
    "詰めぱずる問題選択": "Select a puzzle",
    "○で決定  ×で戻る": "○: OK   ×: Back",
    # memory card
    "セーブ": "Save",
    "ロード": "Load",
    "カードチェック": "Card Check",
    "カードチェック失敗   ○ボタンで次へ": "Card check failed   ○: Next",
    "カード無し警告   ○ボタンで次へ": "No card   ○: Next",
    "未フォーマット警告   ○ボタンで次へ": "Not formatted   ○: Next",
    "容量不足警告   ○ボタンで次へ": "Not enough space   ○: Next",
    "ロードデータ無し警告   ○ボタンで次へ": "No save data   ○: Next",
    # tutorial-style objectives
    "よ～く考えよう!": "Think hard!",
    "全てのたまを消してね！": "Clear all the balls!",
    # debug placeholder
    "あああ": "aaa",
}

# ---- 47-prefecture table -----------------------------------------------------
# The region / home-prefecture names shown in the player profile. They are pure
# kanji, so pntext's is_text() classifier (which keys on kana) skips them and
# they never reach elf.tsv. We add them here as `pref:` rows; pntext.cmd_elf_b
# hands those to patch_prefectures(), which repacks the whole name blob into
# romaji and repoints its char* array (romaji is longer than some 8-byte slots,
# but the full set still fits the original region). Order = pointer-array order.
PREF = [
    (0x329b08, "北海道", "Hokkaido"),  (0x329b10, "青森県", "Aomori"),
    (0x329b18, "岩手県", "Iwate"),     (0x329b20, "宮城県", "Miyagi"),
    (0x329b28, "秋田県", "Akita"),     (0x329b30, "山形県", "Yamagata"),
    (0x329b38, "福島県", "Fukushima"), (0x329b40, "茨城県", "Ibaraki"),
    (0x329b48, "栃木県", "Tochigi"),   (0x329b50, "群馬県", "Gunma"),
    (0x329b58, "埼玉県", "Saitama"),   (0x329b60, "千葉県", "Chiba"),
    (0x329b68, "東京都", "Tokyo"),     (0x329b70, "神奈川県", "Kanagawa"),
    (0x329b80, "新潟県", "Niigata"),   (0x329b88, "富山県", "Toyama"),
    (0x329b90, "石川県", "Ishikawa"),  (0x329b98, "福井県", "Fukui"),
    (0x329ba0, "山梨県", "Yamanashi"), (0x329ba8, "長野県", "Nagano"),
    (0x329bb0, "岐阜県", "Gifu"),      (0x329bb8, "静岡県", "Shizuoka"),
    (0x329bc0, "愛知県", "Aichi"),     (0x329bc8, "三重県", "Mie"),
    (0x329bd0, "滋賀県", "Shiga"),     (0x329bd8, "京都府", "Kyoto"),
    (0x329be0, "大阪府", "Osaka"),     (0x329be8, "兵庫県", "Hyogo"),
    (0x329bf0, "奈良県", "Nara"),      (0x329bf8, "和歌山県", "Wakayama"),
    (0x329c08, "鳥取県", "Tottori"),   (0x329c10, "島根県", "Shimane"),
    (0x329c18, "岡山県", "Okayama"),   (0x329c20, "広島県", "Hiroshima"),
    (0x329c28, "山口県", "Yamaguchi"), (0x329c30, "徳島県", "Tokushima"),
    (0x329c38, "香川県", "Kagawa"),    (0x329c40, "愛媛県", "Ehime"),
    (0x329c48, "高知県", "Kochi"),     (0x329c50, "福岡県", "Fukuoka"),
    (0x329c58, "佐賀県", "Saga"),      (0x329c60, "長崎県", "Nagasaki"),
    (0x329c68, "熊本県", "Kumamoto"),  (0x329c70, "大分県", "Oita"),
    (0x329c78, "宮崎県", "Miyazaki"),  (0x329c80, "鹿児島県", "Kagoshima"),
    (0x329c90, "沖縄県", "Okinawa"),
]


# ---- rank table (shown on the room screen by each player) --------------------
# Pure-kanji, so the is_text() classifier skips them. Fixed-stride 8-byte slots at
# 0x331dc8 (so English must be <=7 bytes - "8 Kyu"/"1 Dan"/"Master"/"God" all fit),
# replaced IN PLACE as normal elf rows (no repack, unlike the prefectures).
RANKS = [
    (0x331dc8, "八級", "8 Kyu", 7), (0x331dd0, "七級", "7 Kyu", 7),
    (0x331dd8, "六級", "6 Kyu", 7), (0x331de0, "五級", "5 Kyu", 7),
    (0x331de8, "四級", "4 Kyu", 7), (0x331df0, "三級", "3 Kyu", 7),
    (0x331df8, "二級", "2 Kyu", 7), (0x331e00, "一級", "1 Kyu", 7),
    (0x331e08, "初段", "1 Dan", 7), (0x331e10, "二段", "2 Dan", 7),
    (0x331e18, "三段", "3 Dan", 7), (0x331e20, "四段", "4 Dan", 7),
    (0x331e28, "五段", "5 Dan", 7), (0x331e30, "六段", "6 Dan", 7),
    (0x331e38, "七段", "7 Dan", 7), (0x331e40, "八段", "8 Dan", 7),
    (0x331e48, "名人", "Master", 7), (0x331e50, " 神 ", "God", 15),
]


# ---- regex patterns for numbered mission objectives --------------------------
def pattern(jp):
    m = re.fullmatch(r"(\d+)連鎖せよ！！", jp)
    if m:
        n = m.group(1)
        return "Make %s chain%s!!" % (n, "" if n == "1" else "s")
    if jp == "全消しせよ！！":
        return "Clear them all!!"
    m = re.fullmatch(r"(\d+)個以上同時に消せ！！", jp)
    if m:
        return "Clear %s+ at once!!" % m.group(1)
    m = re.fullmatch(r"(\d+)個同時に消せ！！", jp)
    if m:
        return "Clear %s at once!!" % m.group(1)
    m = re.fullmatch(r"(\d+)連鎖以上せよ！！", jp)
    if m:
        return "Make %s+ chains!!" % m.group(1)
    m = re.fullmatch(r"(\d+)連鎖してね！", jp)
    if m:
        n = m.group(1)
        return "Make %s chain%s!" % (n, "" if n == "1" else "s")
    m = re.fullmatch(r"同時に(\d+)個のたまを消してね！", jp)
    if m:
        return "Clear %s balls at once!" % m.group(1)
    return None

def main():
    rows = pntext.read_tsv(SRC)
    miss = []
    for r in rows:
        jp = r["jp"]
        en = M.get(jp)
        if en is None:
            en = pattern(jp)
        if en is None:
            # leave untranslated (code-noise rows / anything unmapped)
            r["en"] = ""
            r["note"] = (r["note"] + " [keep] unmapped").strip()
            miss.append(jp)
            continue
        r["en"] = en
    # append the prefecture table (repacked + repointed by pntext.cmd_elf_b)
    for vaddr, jp, en in PREF:
        rows.append({"id": "pref:%08x" % vaddr, "max": 15, "jp": jp, "en": en,
                     "note": "repack 47-prefecture table", "line": 0})
    # append the rank table (plain in-place, fits the 7-byte slots)
    for vaddr, jp, en, mx in RANKS:
        rows.append({"id": "elf:%08x" % vaddr, "max": mx, "jp": jp, "en": en,
                     "note": "rank table", "line": 0})
    pntext.write_tsv(OUT, rows)
    print("wrote %s (%d rows, incl %d prefectures, %d ranks)" % (
        OUT, len(rows), len(PREF), len(RANKS)))
    if miss:
        print("UNMAPPED (%d distinct):" % len(set(miss)))
        for j in sorted(set(miss)):
            print("  ", repr(j))

if __name__ == "__main__":
    main()
