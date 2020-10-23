"""
# coding:utf-8
@Time    : 2020/9/23
@Author  : jiangwei
@mail    : jiangwei1@kylinos.cn
@File    : utils
@Software: PyCharm
"""
import datetime
import hashlib
import http
import os

import json
import random
import re
import urllib
from urllib.parse import urlparse, urljoin
import base64

import execjs
import requests
from flask import current_app, request, redirect, url_for
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from itsdangerous import BadSignature, SignatureExpired
import jieba
import wordcloud as wc
from PIL import Image, ImageDraw, ImageFont

from blogin.extension import db
from blogin.setting import basedir
from imageio import imread

# IP查询工具配置
IP_QUERY = "http://ip-api.com/json/{}?lang=zh-CN&fields=status,message,country,region,regionName,city,lat,lon,query"
IP_REG = '((25[0-5]|2[0-4]\d|((1\d{2})|([1-9]?\d)))\.){3}(25[0-5]|2[0-4]\d|((1\d{2})|([1-9]?\d)))'

# 百度OCR配置
OCR_URL = 'https://aip.baidubce.com/rest/2.0/ocr/v1/'
OCR_TOKEN = '24.487f3dbf8ba5259be2f7b321741f02cf.2592000.1604024498.282335-22776145'
OCR_HEADERS = {'content-type': 'application/x-www-form-urlencoded'}
OCR_CATEGORY = {'文字识别': 'accurate_basic', '身份证识别': 'idcard', '银行卡识别': 'bankcard',
                '驾驶证识别': 'driving_license', '车牌识别': 'license_plate'}
BANK_CARD_TYPE = {0: '不能识别', 1: '借记卡', 2: '信用卡'}
LANGUAGE = {'中文': 'zh-CN', '英文': 'en', '日语': 'ja', '法语': 'fr', '俄语': 'ru'}

TRAN_LANGUAGE = {'英译中': 'zh-CN', '中译英': 'en'}
BAIDU_LANGUAGE = {'英译中': 'zh', '中译英': 'en'}

FONT_COLOR = {'红色': (255, 0, 0, 50), '蓝色': (0, 0, 255, 50), '白色': (255, 255, 255, 50), '黑色': (0, 0, 0, 50)}


class Operations:
    CONFIRM = 'confirm'
    RESET_PASSWORD = 'reset-password'
    CHANGE_EMAIL = 'change-email'


def get_current_time():
    """
    get the current time with yy-mm-dd hh:mm:ss format
    :return: the current time
    """
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_path(path):
    if not os.path.exists(path):
        os.makedirs(path)


def get_ip_real_add(ip):
    if ip == '127.0.0.1':
        return '本地IP'
    response = requests.get(IP_QUERY.format(ip))
    response = response.text
    response = json.loads(response)
    if response['status'] == 'fail':
        return '定位失败'
    return response['country'] + '-' + response['city']


def generate_token(user, operation, expire_in=None, **kwargs):
    s = Serializer(current_app.config['SECRET_KEY'], expire_in)
    data = {'id': user.id, 'operation': operation}
    data.update(**kwargs)
    return s.dumps(data)


def validate_token(user, token, operation, new_password=None):
    s = Serializer(current_app.config['SECRET_KEY'])
    try:
        data = s.loads(token)
    except (SignatureExpired, BadSignature):
        return False
    if operation != data.get('operation') or user.id != data.get('id'):
        return False

    if operation == Operations.CONFIRM:
        user.confirm = 1
    else:
        user.set_password(new_password)
    db.session.commit()

    return True


def generate_ver_code():
    import random
    return random.randint(134299, 873242)


def split_space(string):
    return str(string).split()


def super_split(string, f):
    return str(string).split(f)


def conv_list(string):
    return list(string)


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


def redirect_back(default='blog_bp.index', **kwargs):
    for target in request.args.get('next'), request.referrer:
        if not target:
            continue
        if is_safe_url(target):
            return redirect(target)
    return redirect(url_for(default, **kwargs))


def allow_img_file(filename):
    suffix = filename.split('.')[0]
    if suffix not in ['jpg', 'png', 'jpeg']:
        return False
    return True


def allow_txt_file(filename):
    suffix = filename.split('.')[0]
    if suffix != 'txt':
        return False
    return True


class ImageAddMarkBase:
    def __init__(self, image, text, font_size, save_path, font_color):
        self.image = image
        self.text = text
        self.font_size = font_size
        self.save_path = save_path
        self.font_color = font_color
        self.font = None
        self.font_len = None
        self.image_draw = None
        self.rgba_image = None
        self.text_overlay = None

    def generate_base(self):
        self.font = ImageFont.truetype(basedir + '/res/STFangsong.ttf', self.font_size)
        # 添加背景
        new_img = Image.new('RGBA', (self.image.size[0] * 3, self.image.size[1] * 3), (0, 0, 0, 0))
        new_img.paste(self.image, self.image.size)

        # 添加水印
        self.font_len = len(self.text)
        self.rgba_image = new_img.convert('RGBA')
        self.text_overlay = Image.new('RGBA', self.rgba_image.size, (255, 255, 255, 0))
        self.image_draw = ImageDraw.Draw(self.text_overlay)


def resize_img(path, w_zoom, h_zoom):
    """
    生成缩略图
    :param h_zoom: 高放大比例
    :param w_zoom: 宽放大比例
    :param path: 文件路径
    :return: 返回缩略图，缩小尺寸到原来的三分之一
    """
    img = Image.open(path)
    width = img.size[0]
    height = img.size[1]
    img = img.resize((int(width * w_zoom), int(height * h_zoom)), Image.ANTIALIAS)
    return img


class AddMark2RT(ImageAddMarkBase):
    def __init__(self, *args, **kwargs):
        super(AddMark2RT, self).__init__(*args, **kwargs)
        self.generate_base()

    def generate_mark(self):
        self.image_draw.text((self.image.size[0] * 2 - (self.font_len + 150), self.image.size[1]),
                             self.text, font=self.font, fill=self.font_color)

        image_with_text = Image.alpha_composite(self.rgba_image, self.text_overlay)
        # 裁切图片
        image_with_text = image_with_text.crop(
            (self.image.size[0], self.image.size[1], self.image.size[0] * 2, self.image.size[1] * 2))
        image_with_text.save(self.save_path)


class AddMark2RB(ImageAddMarkBase):
    def __init__(self, *args, **kwargs):
        super(AddMark2RB, self).__init__(*args, **kwargs)
        self.generate_base()

    def generate_mark(self):
        self.image_draw.text((self.image.size[0] * 2 - (self.font_len * self.font_size),
                              self.image.size[1] * 2 - (self.font_len * (self.font_size / 3))),
                             self.text, font=self.font, fill=self.font_color)

        image_with_text = Image.alpha_composite(self.rgba_image, self.text_overlay)
        # 裁切图片
        image_with_text = image_with_text.crop(
            (self.image.size[0], self.image.size[1], self.image.size[0] * 2, self.image.size[1] * 2))
        image_with_text.save(self.save_path)


class AddMark2LT(ImageAddMarkBase):
    def __init__(self, *args, **kwargs):
        super(AddMark2LT, self).__init__(*args, **kwargs)
        self.generate_base()

    def generate_mark(self):
        self.image_draw.text((self.image.size[0], self.image.size[1]),
                             self.text, font=self.font, fill=self.font_color)

        image_with_text = Image.alpha_composite(self.rgba_image, self.text_overlay)
        # 裁切图片
        image_with_text = image_with_text.crop(
            (self.image.size[0], self.image.size[1], self.image.size[0] * 2, self.image.size[1] * 2))
        image_with_text.save(self.save_path)


class AddMark2LB(ImageAddMarkBase):
    def __init__(self, *args, **kwargs):
        super(AddMark2LB, self).__init__(*args, **kwargs)
        self.generate_base()

    def generate_mark(self):
        self.image_draw.text((self.image.size[0], self.image.size[1] * 2 - (self.font_len * (self.font_size / 3))),
                             self.text, font=self.font, fill=self.font_color)

        image_with_text = Image.alpha_composite(self.rgba_image, self.text_overlay)
        # 裁切图片
        image_with_text = image_with_text.crop(
            (self.image.size[0], self.image.size[1], self.image.size[0] * 2, self.image.size[1] * 2))
        image_with_text.save(self.save_path)


class AddMark2Center(ImageAddMarkBase):
    def __init__(self, *args, **kwargs):
        super(AddMark2Center, self).__init__(*args, **kwargs)
        self.generate_base()

    def generate_mark(self):
        self.image_draw.text((self.image.size[0] * 1.5 - self.font_len, self.image.size[1] * 1.5),
                             self.text, font=self.font, fill=self.font_color)

        image_with_text = Image.alpha_composite(self.rgba_image, self.text_overlay)
        # 裁切图片
        image_with_text = image_with_text.crop(
            (self.image.size[0], self.image.size[1], self.image.size[0] * 2, self.image.size[1] * 2))
        image_with_text.save(self.save_path)


class AddMark2Parallel(ImageAddMarkBase):
    def __init__(self, *args, **kwargs):
        super(AddMark2Parallel, self).__init__(*args, **kwargs)
        self.generate_base()

    def generate_mark(self):
        for i in range(0, self.rgba_image.size[0], self.font_len * self.font_size + 50):  # 控制
            for j in range(0, self.rgba_image.size[1], int(self.image.size[1] / 10)):
                self.image_draw.text((i, j), self.text, font=self.font, fill=self.font_color)
        image_with_text = Image.alpha_composite(self.rgba_image, self.text_overlay)
        # 裁切图片
        image_with_text = image_with_text.crop(
            (self.image.size[0], self.image.size[1], self.image.size[0] * 2, self.image.size[1] * 2))
        image_with_text.save(self.save_path)


class AddMark2Rotate(ImageAddMarkBase):
    def __init__(self, *args, **kwargs):
        super(AddMark2Rotate, self).__init__(*args, **kwargs)
        self.generate_base()

    def generate_mark(self):
        for i in range(0, self.rgba_image.size[0], self.font_len * 40 + 50):  # 控制
            for j in range(0, self.rgba_image.size[1], int(self.image.size[1] / 10)):
                self.image_draw.text((i, j), self.text, font=self.font, fill=self.font_color)
        self.text_overlay = self.text_overlay.rotate(-45)
        image_with_text = Image.alpha_composite(self.rgba_image, self.text_overlay)
        # 裁切图片
        image_with_text = image_with_text.crop(
            (self.image.size[0], self.image.size[1], self.image.size[0] * 2, self.image.size[1] * 2))
        image_with_text.save(self.save_path)


def add_mark_to_image(image, text, font_size, save_path, font_color):
    font = ImageFont.truetype(basedir + '/res/STFangsong.ttf', font_size)
    # 添加背景
    new_img = Image.new('RGBA', (image.size[0] * 3, image.size[1] * 3), (0, 0, 0, 0))
    new_img.paste(image, image.size)

    # 添加水印
    font_len = len(text)
    rgba_image = new_img.convert('RGBA')
    text_overlay = Image.new('RGBA', rgba_image.size, (255, 255, 255, 0))
    image_draw = ImageDraw.Draw(text_overlay)

    for i in range(0, rgba_image.size[0], font_len * 40 + 50):
        for j in range(0, rgba_image.size[1], 100):
            image_draw.text((i, j), text, font=font, fill=font_color)

    text_overlay = text_overlay.rotate(-45)
    image_with_text = Image.alpha_composite(rgba_image, text_overlay)

    # 裁切图片
    image_with_text = image_with_text.crop((image.size[0], image.size[1], image.size[0] * 2, image.size[1] * 2))
    image_with_text.save(save_path)


class OCR:
    def __init__(self, filename, category='accurate_basic'):
        self.filename = filename
        self.category = category
        self.url = None
        self.img = None
        self.set_url()
        self.set_img()

    def set_url(self):
        self.url = OCR_URL + OCR_CATEGORY.get(self.category) + "?access_token=" + OCR_TOKEN

    def set_img(self):
        with open(self.filename, 'rb') as f:
            self.img = base64.b64encode(f.read())

    def ocr(self):
        response = requests.post(self.url, data={"image": self.img}, headers=OCR_HEADERS)
        res = response.json()
        nums = res.get("words_result_num")
        texts = ''
        for text in res.get('words_result'):
            texts += text.get('words') + '\n'
        return nums, texts

    def ocr_idcard(self):
        response = requests.post(self.url, data={"id_card_side": "front", "image": self.img}, headers=OCR_HEADERS)
        res = response.json()
        nums = res.get('words_result_num')
        texts = ''
        results = res.get('words_result')
        texts += '姓名:' + results.get('姓名').get('words') + '\n'
        texts += '民族:' + results.get('民族').get('words') + '\n'
        texts += '住址:' + results.get('住址').get('words') + '\n'
        texts += '出生:' + results.get('出生').get('words') + '\n'
        texts += '公民身份号码:' + results.get('公民身份号码').get('words') + '\n'
        texts += '性别:' + results.get('性别').get('words') + '\n'
        return nums, texts

    def ocr_bankcard(self):
        response = requests.post(self.url, data={"image": self.img}, headers=OCR_HEADERS)
        res = response.json()
        card_num = res.get('result').get('bank_card_number')
        validate_date = res.get('result').get('valid_date')
        card_type = BANK_CARD_TYPE.get(res.get('result').get('bank_card_type'))
        bank_name = res.get('result').get('bank_name')
        return 4, '卡号: ' + card_num + '\n' + '有效日期: ' + validate_date + \
               '\n' + '卡种: ' + card_type + '\n' + '所属行: ' + bank_name

    def ocr_drive_card(self):
        response = requests.post(self.url, data={"image": self.img}, headers=OCR_HEADERS)
        res = response.json()
        nums = res.get('words_result_num')
        results = res.get('words_result')
        number = results.get('证号').get('words')
        validate_date = results.get('有效期限').get('words')
        car_type = results.get('准驾车型').get('words')
        # start_date = results.get('有效起始日期').get('words')
        addr = results.get('住址').get('words')
        name = results.get('姓名').get('words')
        country = results.get('国籍').get('words')
        birth = results.get('出生日期').get('words')
        gender = results.get('性别').get('words')
        get_time = results.get('初次领证日期').get('words')

        return nums, '证号: ' + number + '\n' + '有效期限: ' + validate_date + '\n' + '准驾车型: ' + car_type + '\n' + \
               '住址: ' + addr + '\n' + '姓名: ' + name + '\n' + '国籍: ' + country + '\n' + '出生日期: ' + birth + \
               '\n' + '性别: ' + gender + '\n' + '初次领证日期: ' + get_time

    def ocr_license_plate(self):
        response = requests.post(self.url, data={"image": self.img}, headers=OCR_HEADERS)
        res = response.json()
        color = res.get('words_result').get('color')
        number = res.get('words_result').get('number')

        return 0, '车牌颜色: ' + color + '\n' + '车牌号码: ' + number


class IPQuery:
    def __init__(self, ip, lang='zh-CN'):
        self.ip = ip.strip()
        self.lang = LANGUAGE.get(lang)
        self.url = "http://ip-api.com/json/{}?lang={}&fields=status,continent,continentCode,isp,zip,message,timezone," \
                   "country,region,regionName,city,lat,lon,query"

    def query(self):
        if self.ip == '127.0.0.1':
            return '本地IP'
        response = requests.get(self.url.format(self.ip, self.lang))
        response = response.text
        response = json.loads(response)
        if response['status'] == 'fail':
            return '查询失败'
        return [response['country'], response['regionName'], response['city'], response['continent'],
                response['continentCode'], response['isp'], response['timezone'], response['lat'], response['lon']]


class WordCloud:
    def __init__(self, txt=None, img=None):
        self.txt = txt
        self.img = img
        self.words = None

    def cut(self):
        self.words = jieba.cut(self.txt)
        self.words = ' '.join(self.words)

    def generate(self):
        try:
            mask = imread(self.img)
            self.cut()
            w = wc.WordCloud(font_path=basedir + r'/res/STFangsong.ttf', mask=mask, width=len(mask[0]),
                             height=len(mask), background_color="white",
                             max_words=20)
            w.generate(self.words)
            pre = str(datetime.datetime.now()).split(' ')[1].replace(':', '')
            w.to_file(basedir + '/uploads/wordcloud/' + pre + '.jpg')
            return pre + '.jpg'
        except:
            import traceback
            traceback.print_exc()
            return False


class GoogleTranslation:
    def __init__(self):
        self.url = 'https://translate.google.cn/translate_a/single'
        self.TKK = "434674.96463358"  # 随时都有可能需要更新的TKK值

        self.header = {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cookie": "NID=188=M1p_rBfweeI_Z02d1MOSQ5abYsPfZogDrFjKwIUbmAr584bc9GBZkfDwKQ80cQCQC34zwD4ZYHFMUf4F59aDQLSc79_LcmsAihnW0Rsb1MjlzLNElWihv-8KByeDBblR2V1kjTSC8KnVMe32PNSJBQbvBKvgl4CTfzvaIEgkqss",
            "referer": "https://translate.google.cn/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.142 Safari/537.36",
            "x-client-data": "CJK2yQEIpLbJAQjEtskBCKmdygEIqKPKAQi5pcoBCLGnygEI4qjKAQjxqcoBCJetygEIza3KAQ==",
        }

        self.data = {
            "client": "webapp",  # 基于网页访问服务器
            "sl": "auto",  # 源语言,auto表示由谷歌自动识别
            "tl": "vi",  # 翻译的目标语言
            "hl": "zh-CN",  # 界面语言选中文，毕竟URL都是cn后缀了，就不装美国人了
            "dt": ["at", "bd", "ex", "ld", "md", "qca", "rw", "rm", "ss", "t"],  # dt表示要求服务器返回的数据类型
            "otf": "2",
            "ssel": "0",
            "tsel": "0",
            "kc": "1",
            "tk": "",  # 谷歌服务器会核对的token
            "q": ""  # 待翻译的字符串
        }

        with open(basedir + r'/res/token.js', 'r', encoding='utf-8') as f:
            self.js_fun = execjs.compile(f.read())

        # 构建完对象以后要同步更新一下TKK值
        # self.update_TKK()

    def update_TKK(self):
        url = "https://translate.google.cn/"
        req = urllib.request.Request(url=url, headers=self.header)
        page_source = urllib.request.urlopen(req).read().decode("utf-8")
        self.TKK = re.findall(r"tkk:'([0-9]+\.[0-9]+)'", page_source)[0]

    def construct_url(self):
        base = self.url + '?'
        for key in self.data:
            if isinstance(self.data[key], list):
                base = base + "dt=" + "&dt=".join(self.data[key]) + "&"
            else:
                base = base + key + '=' + self.data[key] + '&'
        base = base[:-1]
        return base

    def query(self, q, lang_to=''):
        self.data['q'] = urllib.parse.quote(q)
        self.data['tk'] = self.js_fun.call('wo', q, self.TKK)
        self.data['tl'] = lang_to
        url = self.construct_url()
        req = urllib.request.Request(url=url, headers=self.header)
        response = json.loads(urllib.request.urlopen(req).read().decode("utf-8"))
        target_text = response[0][0][0]
        return target_text


class BaiduTranslation:
    def __init__(self, q, lang='en'):
        self.app_id = current_app.config.get('BAIDU_TRANS_APPID')
        self.key = current_app.config.get('BAIDU_TRANS_KEY')
        self.pre_url = '/api/trans/vip/translate'
        self.from_lang = 'auto'
        self.to_lang = lang
        self.http_client = None
        self.salt = random.randint(32768, 65536)
        sign = self.app_id + q + str(self.salt) + self.key
        sign = hashlib.md5(sign.encode()).hexdigest()
        self.url = self.pre_url + '?appid=' + self.app_id + '&q=' + urllib.parse.quote(
            q) + '&from=' + self.from_lang + '&to=' + self.to_lang + '&salt=' + str(
            self.salt) + '&sign=' + sign

    def query(self):
        try:
            self.http_client = http.client.HTTPConnection('api.fanyi.baidu.com')
            self.http_client.request('GET', self.url)
            response = self.http_client.getresponse()
            result_all = response.read().decode("utf-8")
            result = json.loads(result_all)
            trans = result.get('trans_result')[0].get('dst')
            return trans
        except:
            return False
        finally:
            if self.http_client:
                self.http_client.close()


class YoudaoTranslation:
    def __init__(self, q, from_lang='auto', to_lang='zh'):
        # 翻译地址
        request_url = 'http://fanyi.youdao.com/translate?smartresult=dict&smartresult=rule'
        # data参数
        data = {'i': q,
                'from': from_lang,
                'to': to_lang,
                'smartresult': 'dict',
                'client': 'fanyideskweb',
                'salt': '15944508027607',
                'sign': '598c09b218f668874be4524f19e0be37',
                'ts': '1594450802760',
                'bv': '02a6ad4308a3443b3732d855273259bf',
                'doctype': 'json',
                'version': '2.1',
                'keyfrom': 'fanyi.web',
                'action': 'FY_BY_REALTlME',
                }
        # headers参数
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.116 Safari/537.36'}
        # 将data规范化
        data = urllib.parse.urlencode(data)
        # 转为字节型
        data = bytes(data, 'utf-8')
        # 创建请求
        req = urllib.request.Request(request_url, data, headers=headers)
        # 发送请求并获取相应
        response = urllib.request.urlopen(req)
        # 返回内容,得到一个json字符串
        html = response.read().decode('utf-8')
        # 将json字符串转为字典
        html = json.loads(html)
        self.result = html['translateResult'][0][0]['tgt']

    def query(self):
        return self.result


class Lunar(object):
    # ******************************************************************************
    # 下面为阴历计算所需的数据,为节省存储空间,所以采用下面比较变态的存储方法.
    # ******************************************************************************
    # 数组g_lunar_month_day存入阴历1901年到2050年每年中的月天数信息，
    # 阴历每月只能是29或30天，一年用12（或13）个二进制位表示，对应位为1表30天，否则为29天
    g_lunar_month_day = [
        0x4ae0, 0xa570, 0x5268, 0xd260, 0xd950, 0x6aa8, 0x56a0, 0x9ad0, 0x4ae8, 0x4ae0,  # 1910
        0xa4d8, 0xa4d0, 0xd250, 0xd548, 0xb550, 0x56a0, 0x96d0, 0x95b0, 0x49b8, 0x49b0,  # 1920
        0xa4b0, 0xb258, 0x6a50, 0x6d40, 0xada8, 0x2b60, 0x9570, 0x4978, 0x4970, 0x64b0,  # 1930
        0xd4a0, 0xea50, 0x6d48, 0x5ad0, 0x2b60, 0x9370, 0x92e0, 0xc968, 0xc950, 0xd4a0,  # 1940
        0xda50, 0xb550, 0x56a0, 0xaad8, 0x25d0, 0x92d0, 0xc958, 0xa950, 0xb4a8, 0x6ca0,  # 1950
        0xb550, 0x55a8, 0x4da0, 0xa5b0, 0x52b8, 0x52b0, 0xa950, 0xe950, 0x6aa0, 0xad50,  # 1960
        0xab50, 0x4b60, 0xa570, 0xa570, 0x5260, 0xe930, 0xd950, 0x5aa8, 0x56a0, 0x96d0,  # 1970
        0x4ae8, 0x4ad0, 0xa4d0, 0xd268, 0xd250, 0xd528, 0xb540, 0xb6a0, 0x96d0, 0x95b0,  # 1980
        0x49b0, 0xa4b8, 0xa4b0, 0xb258, 0x6a50, 0x6d40, 0xada0, 0xab60, 0x9370, 0x4978,  # 1990
        0x4970, 0x64b0, 0x6a50, 0xea50, 0x6b28, 0x5ac0, 0xab60, 0x9368, 0x92e0, 0xc960,  # 2000
        0xd4a8, 0xd4a0, 0xda50, 0x5aa8, 0x56a0, 0xaad8, 0x25d0, 0x92d0, 0xc958, 0xa950,  # 2010
        0xb4a0, 0xb550, 0xb550, 0x55a8, 0x4ba0, 0xa5b0, 0x52b8, 0x52b0, 0xa930, 0x74a8,  # 2020
        0x6aa0, 0xad50, 0x4da8, 0x4b60, 0x9570, 0xa4e0, 0xd260, 0xe930, 0xd530, 0x5aa0,  # 2030
        0x6b50, 0x96d0, 0x4ae8, 0x4ad0, 0xa4d0, 0xd258, 0xd250, 0xd520, 0xdaa0, 0xb5a0,  # 2040
        0x56d0, 0x4ad8, 0x49b0, 0xa4b8, 0xa4b0, 0xaa50, 0xb528, 0x6d20, 0xada0, 0x55b0,  # 2050
    ]

    # 数组gLanarMonth存放阴历1901年到2050年闰月的月份，如没有则为0，每字节存两年
    g_lunar_month = [
        0x00, 0x50, 0x04, 0x00, 0x20,  # 1910
        0x60, 0x05, 0x00, 0x20, 0x70,  # 1920
        0x05, 0x00, 0x40, 0x02, 0x06,  # 1930
        0x00, 0x50, 0x03, 0x07, 0x00,  # 1940
        0x60, 0x04, 0x00, 0x20, 0x70,  # 1950
        0x05, 0x00, 0x30, 0x80, 0x06,  # 1960
        0x00, 0x40, 0x03, 0x07, 0x00,  # 1970
        0x50, 0x04, 0x08, 0x00, 0x60,  # 1980
        0x04, 0x0a, 0x00, 0x60, 0x05,  # 1990
        0x00, 0x30, 0x80, 0x05, 0x00,  # 2000
        0x40, 0x02, 0x07, 0x00, 0x50,  # 2010
        0x04, 0x09, 0x00, 0x60, 0x04,  # 2020
        0x00, 0x20, 0x60, 0x05, 0x00,  # 2030
        0x30, 0xb0, 0x06, 0x00, 0x50,  # 2040
        0x02, 0x07, 0x00, 0x50, 0x03  # 2050
    ]

    START_YEAR = 1901

    # 天干
    gan = '甲乙丙丁戊己庚辛壬癸'
    # 地支
    zhi = '子丑寅卯辰巳午未申酉戌亥'
    # 生肖
    xiao = '鼠牛虎兔龙蛇马羊猴鸡狗猪'
    # 月份
    lm = '正二三四五六七八九十冬腊'
    # 日份
    ld = '初一初二初三初四初五初六初七初八初九初十十一十二十三十四十五十六十七十八十九二十廿一廿二廿三廿四廿五廿六廿七廿八廿九三十'
    # 节气
    jie = '小寒大寒立春雨水惊蛰春分清明谷雨立夏小满芒种夏至小暑大暑立秋处暑白露秋分寒露霜降立冬小雪大雪冬至'

    def __init__(self, dt=None):
        '''初始化：参数为datetime.datetime类实例，默认当前时间'''
        self.localtime = dt if dt else datetime.datetime.today()

    def sx_year(self):  # 返回生肖年
        ct = self.localtime  # 取当前时间

        year = self.ln_year() - 3 - 1  # 农历年份减3 （说明：补减1）
        year = year % 12  # 模12，得到地支数
        return self.xiao[year]

    def gz_year(self):  # 返回干支纪年
        ct = self.localtime  # 取当前时间
        year = self.ln_year() - 3 - 1  # 农历年份减3 （说明：补减1）
        G = year % 10  # 模10，得到天干数
        Z = year % 12  # 模12，得到地支数
        return self.gan[G] + self.zhi[Z]

    def gz_month(self):  # 返回干支纪月（未实现）
        pass

    def gz_day(self):  # 返回干支纪日
        ct = self.localtime  # 取当前时间
        C = ct.year // 100  # 取世纪数，减一
        y = ct.year % 100  # 取年份后两位（若为1月、2月则当前年份减一）
        y = y - 1 if ct.month == 1 or ct.month == 2 else y
        M = ct.month  # 取月份（若为1月、2月则分别按13、14来计算）
        M = M + 12 if ct.month == 1 or ct.month == 2 else M
        d = ct.day  # 取日数
        i = 0 if ct.month % 2 == 1 else 6  # 取i （奇数月i=0，偶数月i=6）

        # 下面两个是网上的公式
        # http://baike.baidu.com/link?url=MbTKmhrTHTOAz735gi37tEtwd29zqE9GJ92cZQZd0X8uFO5XgmyMKQru6aetzcGadqekzKd3nZHVS99rewya6q
        # 计算干（说明：补减1）
        G = 4 * C + C // 4 + 5 * y + y // 4 + 3 * (M + 1) // 5 + d - 3 - 1
        G = G % 10
        # 计算支（说明：补减1）
        Z = 8 * C + C // 4 + 5 * y + y // 4 + 3 * (M + 1) // 5 + d + 7 + i - 1
        Z = Z % 12

        # 返回 干支纪日
        return self.gan[G] + self.zhi[Z]

    def gz_hour(self):  # 返回干支纪时（时辰）
        ct = self.localtime  # 取当前时间
        # 计算支
        Z = round((ct.hour / 2) + 0.1) % 12  # 之所以加0.1是因为round的bug!!

        # 返回 干支纪时（时辰）
        return self.zhi[Z]

    def ln_year(self):  # 返回农历年
        year, _, _ = self.ln_date()
        return year

    def ln_month(self):  # 返回农历月
        _, month, _ = self.ln_date()
        return month

    def ln_day(self):  # 返回农历日
        _, _, day = self.ln_date()
        return day

    def ln_date(self):  # 返回农历日期整数元组（年、月、日）（查表法）
        delta_days = self._date_diff()

        # 阳历1901年2月19日为阴历1901年正月初一
        # 阳历1901年1月1日到2月19日共有49天
        if (delta_days < 49):
            year = self.START_YEAR - 1
            if (delta_days < 19):
                month = 11;
                day = 11 + delta_days
            else:
                month = 12;
                day = delta_days - 18
            return (year, month, day)

        # 下面从阴历1901年正月初一算起
        delta_days -= 49
        year, month, day = self.START_YEAR, 1, 1
        # 计算年
        tmp = self._lunar_year_days(year)
        while delta_days >= tmp:
            delta_days -= tmp
            year += 1
            tmp = self._lunar_year_days(year)

        # 计算月
        (foo, tmp) = self._lunar_month_days(year, month)
        while delta_days >= tmp:
            delta_days -= tmp
            if (month == self._get_leap_month(year)):
                (tmp, foo) = self._lunar_month_days(year, month)
                if (delta_days < tmp):
                    return (0, 0, 0)
                delta_days -= tmp
            month += 1
            (foo, tmp) = self._lunar_month_days(year, month)

        # 计算日
        day += delta_days
        return (year, month, day)

    def ln_date_str(self):  # 返回农历日期字符串，形如：农历正月初九
        _, month, day = self.ln_date()
        return '农历{}月{}'.format(self.lm[month - 1], self.ld[(day - 1) * 2:day * 2])

    def ln_jie(self):  # 返回农历节气
        ct = self.localtime  # 取当前时间
        year = ct.year
        for i in range(24):
            # 因为两个都是浮点数，不能用相等表示
            delta = self._julian_day() - self._julian_day_of_ln_jie(year, i)
            if -.5 <= delta <= .5:
                return self.jie[i * 2:(i + 1) * 2]
        return ''

    # 显示日历
    def calendar(self):
        pass

    #######################################################
    #            下面皆为私有函数
    #######################################################

    def _date_diff(self):
        '''返回基于1901/01/01日差数'''
        return (self.localtime - datetime.datetime(1901, 1, 1)).days

    def _get_leap_month(self, lunar_year):
        flag = self.g_lunar_month[(lunar_year - self.START_YEAR) // 2]
        if (lunar_year - self.START_YEAR) % 2:
            return flag & 0x0f
        else:
            return flag >> 4

    def _lunar_month_days(self, lunar_year, lunar_month):
        if lunar_year < self.START_YEAR:
            return 30

        high, low = 0, 29
        iBit = 16 - lunar_month;

        if lunar_month > self._get_leap_month(lunar_year) and self._get_leap_month(lunar_year):
            iBit -= 1

        if self.g_lunar_month_day[lunar_year - self.START_YEAR] & (1 << iBit):
            low += 1

        if lunar_month == self._get_leap_month(lunar_year):
            if self.g_lunar_month_day[lunar_year - self.START_YEAR] & (1 << (iBit - 1)):
                high = 30
            else:
                high = 29

        return high, low

    def _lunar_year_days(self, year):
        days = 0
        for i in range(1, 13):
            (high, low) = self._lunar_month_days(year, i)
            days += high
            days += low
        return days

    # 返回指定公历日期的儒略日（http://blog.csdn.net/orbit/article/details/9210413）
    def _julian_day(self):
        ct = self.localtime  # 取当前时间
        year = ct.year
        month = ct.month
        day = ct.day

        if month <= 2:
            month += 12
            year -= 1

        B = year / 100
        B = 2 - B + year / 400

        dd = day + 0.5000115740  # 本日12:00后才是儒略日的开始(过一秒钟)*/
        return int(365.25 * (year + 4716) + 0.01) + int(30.60001 * (month + 1)) + dd + B - 1524.5

    # 返回指定年份的节气的儒略日数（http://blog.csdn.net/orbit/article/details/9210413）
    def _julian_day_of_ln_jie(self, year, st):
        s_stAccInfo = [
            0.00, 1272494.40, 2548020.60, 3830143.80, 5120226.60, 6420865.80,
            7732018.80, 9055272.60, 10388958.00, 11733065.40, 13084292.40, 14441592.00,
            15800560.80, 17159347.20, 18513766.20, 19862002.20, 21201005.40, 22529659.80,
            23846845.20, 25152606.00, 26447687.40, 27733451.40, 29011921.20, 30285477.60]

        # 已知1900年小寒时刻为1月6日02:05:00
        base1900_SlightColdJD = 2415025.5868055555

        if (st < 0) or (st > 24):
            return 0.0

        stJd = 365.24219878 * (year - 1900) + s_stAccInfo[st] / 86400.0

        return base1900_SlightColdJD + stJd