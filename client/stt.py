#!/usr/bin/env python2
# -*- coding: utf-8-*-
from __future__ import print_function
from __future__ import absolute_import
import os
import base64
import wave
import json
import urlparse
import tempfile
import logging
import urllib
from abc import ABCMeta, abstractmethod
import requests
import yaml
from . import dingdangpath
from . import diagnose
from . import vocabcompiler
from uuid import getnode as get_mac
import hashlib
import datetime
import hmac
import sys
from dateutil import parser as dparser

from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

try:
    reload         # Python 2
except NameError:  # Python 3
    from importlib import reload

reload(sys)
sys.setdefaultencoding('utf8')


class AbstractSTTEngine(object):
    """
    Generic parent class for all STT engines
    """

    __metaclass__ = ABCMeta
    VOCABULARY_TYPE = None

    @classmethod
    def get_config(cls):
        return {}

    @classmethod
    def get_instance(cls, vocabulary_name, phrases):
        config = cls.get_config()
        if cls.VOCABULARY_TYPE:
            vocabulary = cls.VOCABULARY_TYPE(vocabulary_name,
                                             path=dingdangpath.config(
                                                 'vocabularies'))
            if not vocabulary.matches_phrases(phrases):
                vocabulary.compile(phrases)
            config['vocabulary'] = vocabulary
        instance = cls(**config)
        return instance

    @classmethod
    def get_passive_instance(cls):
        phrases = vocabcompiler.get_keyword_phrases()
        return cls.get_instance('keyword', phrases)

    @classmethod
    def get_active_instance(cls):
        phrases = vocabcompiler.get_all_phrases()
        return cls.get_instance('default', phrases)

    @classmethod
    def get_music_instance(cls):
        phrases = vocabcompiler.get_all_phrases()
        return cls.get_instance('music', phrases)

    @classmethod
    @abstractmethod
    def is_available(cls):
        return True

    @abstractmethod
    def transcribe(self, fp):
        pass

    @classmethod
    def transcribe_keyword(self, fp):
        pass


class PocketSphinxSTT(AbstractSTTEngine):
    """
    The default Speech-to-Text implementation which relies on PocketSphinx.
    """

    SLUG = 'sphinx'
    VOCABULARY_TYPE = vocabcompiler.PocketsphinxVocabulary

    def __init__(self, vocabulary, hmm_dir="/usr/local/share/" +
                 "pocketsphinx/model/hmm/en_US/hub4wsj_sc_8k"):
        """
        Initiates the pocketsphinx instance.

        Arguments:
            vocabulary -- a PocketsphinxVocabulary instance
            hmm_dir -- the path of the Hidden Markov Model (HMM)
        """

        self._logger = logging.getLogger(__name__)

        # quirky bug where first import doesn't work
        try:
            import pocketsphinx as ps
        except Exception:
            import pocketsphinx as ps

        with tempfile.NamedTemporaryFile(prefix='psdecoder_',
                                         suffix='.log', delete=False) as f:
            self._logfile = f.name

        self._logger.debug("Initializing PocketSphinx Decoder with hmm_dir " +
                           "'%s'", hmm_dir)

        # Perform some checks on the hmm_dir so that we can display more
        # meaningful error messages if neccessary
        if not os.path.exists(hmm_dir):
            msg = ("hmm_dir '%s' does not exist! Please make sure that you " +
                   "have set the correct hmm_dir in your profile.") % hmm_dir
            self._logger.error(msg)
            raise RuntimeError(msg)
        # Lets check if all required files are there. Refer to:
        # http://cmusphinx.sourceforge.net/wiki/acousticmodelformat
        # for details
        missing_hmm_files = []
        for fname in ('mdef', 'feat.params', 'means', 'noisedict',
                      'transition_matrices', 'variances'):
            if not os.path.exists(os.path.join(hmm_dir, fname)):
                missing_hmm_files.append(fname)
        mixweights = os.path.exists(os.path.join(hmm_dir, 'mixture_weights'))
        sendump = os.path.exists(os.path.join(hmm_dir, 'sendump'))
        if not mixweights and not sendump:
            # We only need mixture_weights OR sendump
            missing_hmm_files.append('mixture_weights or sendump')
        if missing_hmm_files:
            self._logger.warning("hmm_dir '%s' is missing files: %s. Please " +
                                 "make sure that you have set the correct " +
                                 "hmm_dir in your profile.",
                                 hmm_dir, ', '.join(missing_hmm_files))

        self._decoder = ps.Decoder(hmm=hmm_dir, logfn=self._logfile,
                                   **vocabulary.decoder_kwargs)

    def __del__(self):
        os.remove(self._logfile)

    @classmethod
    def get_config(cls):
        # FIXME: Replace this as soon as we have a config module
        config = {}
        # HMM dir
        # Try to get hmm_dir from config
        profile_path = dingdangpath.config('profile.yml')

        if os.path.exists(profile_path):
            with open(profile_path, 'r') as f:
                profile = yaml.safe_load(f)
                try:
                    config['hmm_dir'] = profile['pocketsphinx']['hmm_dir']
                except KeyError:
                    pass

        return config

    def transcribe(self, fp):
        """
        Performs STT, transcribing an audio file and returning the result.

        Arguments:
            fp -- a file object containing audio data
        """

        fp.seek(44)

        # FIXME: Can't use the Decoder.decode_raw() here, because
        # pocketsphinx segfaults with tempfile.SpooledTemporaryFile()
        data = fp.read()
        self._decoder.start_utt()
        self._decoder.process_raw(data, False, True)
        self._decoder.end_utt()

        result = self._decoder.get_hyp()
        with open(self._logfile, 'r+') as f:
            for line in f:
                self._logger.debug(line.strip())
            f.truncate()

        transcribed = [result[0]]
        self._logger.info('PocketSphinx 识别到了：%r', transcribed)
        return transcribed

    def transcribe_keyword(self, data):
        """
        Performs STT, transcribing the keyword audio file
        and returning the result.

        Arguments:
            data -- a stream object containing audio data
        """

        # FIXME: Can't use the Decoder.decode_raw() here, because
        # pocketsphinx segfaults with tempfile.SpooledTemporaryFile()
        self._decoder.start_utt()
        self._decoder.process_raw(data, False, True)
        self._decoder.end_utt()

        result = self._decoder.get_hyp()

        transcribed = [result[0]]
        self._logger.info('PocketSphinx 识别到了：%r', transcribed)
        return transcribed

    @classmethod
    def is_available(cls):
        return diagnose.check_python_import('pocketsphinx')


class BaiduSTT(AbstractSTTEngine):
    """
    百度的语音识别API.
    要使用本模块, 首先到 yuyin.baidu.com 注册一个开发者账号,
    之后创建一个新应用, 然后在应用管理的"查看key"中获得 API Key 和 Secret Key
    填入 profile.xml 中.
    ...
        baidu_yuyin: 'AIzaSyDoHmTEToZUQrltmORWS4Ott0OHVA62tw8'
            api_key: 'LMFYhLdXSSthxCNLR7uxFszQ'
            secret_key: '14dbd10057xu7b256e537455698c0e4e'
        ...
    """

    SLUG = "baidu-stt"

    def __init__(self, api_key, secret_key):
        self._logger = logging.getLogger(__name__)
        self.api_key = api_key
        self.secret_key = secret_key
        self.token = ''

    @classmethod
    def get_config(cls):
        # FIXME: Replace this as soon as we have a config module
        config = {}
        # Try to get baidu_yuyin config from config
        profile_path = dingdangpath.config('profile.yml')
        if os.path.exists(profile_path):
            with open(profile_path, 'r') as f:
                profile = yaml.safe_load(f)
                if 'baidu_yuyin' in profile:
                    if 'api_key' in profile['baidu_yuyin']:
                        config['api_key'] = \
                            profile['baidu_yuyin']['api_key']
                    if 'secret_key' in profile['baidu_yuyin']:
                        config['secret_key'] = \
                            profile['baidu_yuyin']['secret_key']
        return config

    def get_token(self):
        cache = open(os.path.join(dingdangpath.TEMP_PATH, 'baidustt.ini'),
                     'a+')
        try:
            pms = cache.readlines()
            if len(pms) > 0:
                time = pms[0]
                tk = pms[1]
                # 计算token是否过期 官方说明一个月，这里保守29天
                time = dparser.parse(time)
                endtime = datetime.datetime.now()
                if (endtime - time).days <= 29:
                    return tk
        finally:
            cache.close()
        URL = 'http://openapi.baidu.com/oauth/2.0/token'
        params = urllib.urlencode({'grant_type': 'client_credentials',
                                   'client_id': self.api_key,
                                   'client_secret': self.secret_key})
        r = requests.get(URL, params=params)
        try:
            r.raise_for_status()
            token = r.json()['access_token']
            return token
        except requests.exceptions.HTTPError:
            self._logger.critical('Token request failed with response: %r',
                                  r.text,
                                  exc_info=True)
            return ''

    def transcribe(self, fp):
        try:
            wav_file = wave.open(fp, 'rb')
        except IOError:
            self._logger.critical('wav file not found: %s',
                                  fp,
                                  exc_info=True)
            return []
        n_frames = wav_file.getnframes()
        frame_rate = wav_file.getframerate()
        audio = wav_file.readframes(n_frames)
        base_data = base64.b64encode(audio)
        if self.token == '':
            self.token = self.get_token()
        data = {"format": "wav",
                "token": self.token,
                "len": len(audio),
                "rate": frame_rate,
                "speech": base_data,
                "cuid": str(get_mac())[:32],
                "channel": 1}
        data = json.dumps(data)
        r = requests.post('http://vop.baidu.com/server_api',
                          data=data,
                          headers={'content-type': 'application/json'})
        try:
            r.raise_for_status()
            text = ''
            if 'result' in r.json():
                text = r.json()['result'][0].encode('utf-8')
        except requests.exceptions.HTTPError:
            self._logger.critical('Request failed with response: %r',
                                  r.text,
                                  exc_info=True)
            return []
        except requests.exceptions.RequestException:
            self._logger.critical('Request failed.', exc_info=True)
            return []
        except ValueError as e:
            self._logger.critical('Cannot parse response: %s',
                                  e.args[0])
            return []
        except KeyError:
            self._logger.critical('Cannot parse response.',
                                  exc_info=True)
            return []
        else:
            transcribed = []
            if text:
                transcribed.append(text.upper())
            self._logger.info(u'百度语音识别到了: %s' % text)
            return transcribed

    @classmethod
    def is_available(cls):
        return diagnose.check_network_connection()


class IFlyTekSTT(AbstractSTTEngine):
    """
    科大讯飞的语音识别API.
    要使用本模块, 首先到 http://aiui.xfyun.cn/default/index 注册一个开发者账号,
    之后创建一个新应用, 然后在应用管理的那查看 API id 和 API Key
    填入 profile.xml 中.
    """

    SLUG = "iflytek-stt"

    def __init__(self, api_id, api_key, url):
        self._logger = logging.getLogger(__name__)
        self.api_id = api_id
        self.api_key = api_key
        self.url = url

    @classmethod
    def get_config(cls):
        # FIXME: Replace this as soon as we have a config module
        config = {}
        # Try to get iflytek_yuyin config from config
        profile_path = dingdangpath.config('profile.yml')
        if os.path.exists(profile_path):
            with open(profile_path, 'r') as f:
                profile = yaml.safe_load(f)
                if 'iflytek_yuyin' in profile:
                    if 'api_id' in profile['iflytek_yuyin']:
                        config['api_id'] = \
                            profile['iflytek_yuyin']['api_id']
                    if 'api_key' in profile['iflytek_yuyin']:
                        config['api_key'] = \
                            profile['iflytek_yuyin']['api_key']
                    if 'url' in profile['iflytek_yuyin']:
                        config['url'] = \
                            profile['iflytek_yuyin']['url']
        return config

    def transcribe(self, fp):
        try:
            wav_file = wave.open(fp, 'rb')
        except IOError:
            self._logger.critical('wav file not found: %s',
                                  fp,
                                  exc_info=True)
            return []
        n_frames = wav_file.getnframes()
        frame_rate = wav_file.getframerate()
        Param = str({
            "auf": "16k",
            "aue": "raw",
            "scene": "main",
            "sample_rate": "%s" % str(frame_rate)
        })
        XParam = base64.b64encode(Param)
        audio = wav_file.readframes(n_frames)
        base_data = base64.b64encode(audio)
        data = {
            'voice_data': base_data,
            'api_id': self.api_id,
            'api_key': self.api_key,
            'sample_rate': frame_rate,
            'XParam': XParam
        }
        r = requests.post(self.url, data=data)
        try:
            r.raise_for_status()
            text = ''
            if r.json()['code'] == '00000':
                text = r.json()['data']['result'].encode('utf-8')
        except requests.exceptions.HTTPError:
            self._logger.critical('Request failed with response: %r',
                                  r.text,
                                  exc_info=True)
            return []
        except requests.exceptions.RequestException:
            self._logger.critical('Request failed.', exc_info=True)
            return []
        except ValueError as e:
            self._logger.critical('Cannot parse response: %s',
                                  e.args[0])
            return []
        except KeyError:
            self._logger.critical('Cannot parse response.',
                                  exc_info=True)
            return []
        else:
            self._logger.warning('Cannot parse response.(code: %s)' %
                                 r.json()['code'])
            transcribed = []
            if text:
                transcribed.append(text.upper())
            self._logger.info(u'讯飞语音识别到了: %s' % text)
            return transcribed

    @classmethod
    def is_available(cls):
        return diagnose.check_network_connection()


def get_engine_by_slug(slug=None):
    """
    Returns:
        An STT Engine implementation available on the current platform

    Raises:
        ValueError if no speaker implementation is supported on this platform
    """

    if not slug or type(slug) is not str:
        raise TypeError("Invalid slug '%s'", slug)

    selected_engines = filter(lambda engine: hasattr(engine, "SLUG") and
                              engine.SLUG == slug, get_engines())
    if len(selected_engines) == 0:
        raise ValueError("No STT engine found for slug '%s'" % slug)
    else:
        if len(selected_engines) > 1:
            print(("WARNING: Multiple STT engines found for slug '%s'. " +
                   "This is most certainly a bug.") % slug)
        engine = selected_engines[0]
        if not engine.is_available():
            raise ValueError(("STT engine '%s' is not available (due to " +
                              "missing dependencies, missing " +
                              "dependencies, etc.)") % slug)
        return engine


def get_engines():
    def get_subclasses(cls):
        subclasses = set()
        for subclass in cls.__subclasses__():
            subclasses.add(subclass)
            subclasses.update(get_subclasses(subclass))
        return subclasses
    return [tts_engine for tts_engine in
            list(get_subclasses(AbstractSTTEngine))
            if hasattr(tts_engine, 'SLUG') and tts_engine.SLUG]