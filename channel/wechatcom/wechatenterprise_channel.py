# encoding:utf-8

"""
WechatEnterprise channel
"""
import time
from concurrent.futures import ThreadPoolExecutor
from common.singleton import singleton
from common.log import logger
from config import conf
from bridge.reply import *
from bridge.context import *
from channel.channel import Channel

from wechatpy.enterprise.crypto import WeChatCrypto
from wechatpy.enterprise import WeChatClient
from wechatpy.exceptions import InvalidSignatureException
from wechatpy.enterprise.exceptions import InvalidCorpIdException
from wechatpy.enterprise import parse_message
from flask import Flask, request, abort

thread_pool = ThreadPoolExecutor(max_workers=8)
app = Flask(__name__)


@app.route('/wechat', methods=['GET', 'POST'])
def handler_msg():
    return WechatEnterpriseChannel().handle_text()


@singleton
class WechatEnterpriseChannel(Channel):

    def __init__(self):
        self.CorpId = conf().get('wechat_corp_id')
        self.Secret = conf().get('secret')
        self.AppId = conf().get('appid')
        self.TOKEN = conf().get('wechat_token')
        self.EncodingAESKey = conf().get('wechat_encoding_aes_key')
        self.crypto = WeChatCrypto(self.TOKEN, self.EncodingAESKey, self.CorpId)
        self.client = WeChatClient(self.CorpId, self.Secret, self.AppId)

    def startup(self):
        # start message listener
        app.run(host='0.0.0.0', port=8888)

    def send(self, reply: Reply, context: Context):
        logger.info('[WXCOM] sendMsg={}, receiver={}'.format(context.content, context.source))
        self.client.message.send_text(self.AppId, context.source, context.content)

    # def _do_send(self, query, reply_user_id):
    def _do_send(self, reply: Reply, msg, retry_cnt=0):
        try:
            if not reply:
                return
            # context = dict()
            # context['from_user_id'] = reply_user_id
            if msg.type == "text":
                context = Context(ContextType.TEXT, msg)
                reply_text = super().build_reply_content(msg.content, context)
                if reply_text:
                    self.send(reply_text, context)
            else:
                return
        except Exception as e:
            logger.error('[WX] sendMsg error: {}'.format(str(e)))
            if isinstance(e, NotImplementedError):
                return
            logger.exception(e)
            if retry_cnt < 2:
                time.sleep(3 + 3 * retry_cnt)
                self._send(reply, msg, retry_cnt + 1)

    def handle_text(self):
        query_params = request.args
        signature = query_params.get('msg_signature', '')
        timestamp = query_params.get('timestamp', '')
        nonce = query_params.get('nonce', '')
        if request.method == 'GET':
            # 处理验证请求
            echostr = query_params.get('echostr', '')
            try:
                echostr = self.crypto.check_signature(signature, timestamp, nonce, echostr)
            except InvalidSignatureException:
                abort(403)
            print(echostr)
            return echostr
        elif request.method == 'POST':
            try:
                message = self.crypto.decrypt_message(
                    request.data,
                    signature,
                    timestamp,
                    nonce
                )
            except (InvalidSignatureException, InvalidCorpIdException):
                abort(403)
            msg = parse_message(message)
            if msg.type == 'text':
                reply = '收到'
                thread_pool.submit(self._do_send, msg.content, msg, retry_cnt=0)
            else:
                reply = 'Can not handle this for now'
            self.client.message.send_text(self.AppId, msg.source, reply)
            return 'success'
