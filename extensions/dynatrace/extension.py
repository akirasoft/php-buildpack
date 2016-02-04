# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Dynatrace Extension

Downloads, installs and configures the Dynatrace PHP and Webserver Agents
"""
import os
import subprocess
import os.path
import logging


_log = logging.getLogger('dynatrace')


DEFAULTS = {
    'DYNATRACE_HOST': 'www.akirasoft.com',
    'DYNATRACE_VERSION': '6.2.0.1239',
    'DYNATRACE_PACKAGE': 'dynatrace-wsagent-{DYNATRACE_VERSION}-linux-x64.tar.gz',
    'DYNATRACE_DOWNLOAD_URL': 'http://{DYNATRACE_HOST}/cf/'
                             '{DYNATRACE_PACKAGE}',
}


class DynatraceInstaller(object):
    def __init__(self, ctx):
        self._log = _log
        self._ctx = ctx
        self._detected = False
        self.app_name = None
        self.dynatrace_server = None
        try:
            self._log.info("Initializing")
            if ctx['PHP_VM'] == 'php':
                self._merge_defaults()
                self._load_service_info()
                self._load_php_info()
                self._load_httpd_info()
                self._load_dtwsagent_ini_info()
                self._load_dynatrace_info()
        except Exception:
            self._log.exception("Error installing Dynatrace! "
                                "Dynatrace will not be available.")

    def _merge_defaults(self):
        for key, val in DEFAULTS.iteritems():
            if key not in self._ctx:
                self._ctx[key] = val

    def _load_service_info(self):
        services = self._ctx.get('VCAP_SERVICES', {})
        service_defs = services.get('dynatrace', [])
        if len(service_defs) == 0:
            self._log.info("Dynatrace services not detected, looking for user provided")
            service_defs= services.get('user-provided', [])
        if len(service_defs) > 1:
            self._log.warn("Multiple Dynatrace services found, "
                           "credentials from first one.")
        if len(service_defs) > 0:
            service = service_defs[0]
            creds = service.get('credentials', {})
            self.server = creds.get('server', None)
            if self.server:
                self._log.info("Dynatrace service detected.")
                self._detected = True

    def _load_dynatrace_info(self):
        vcap_app = self._ctx.get('VCAP_APPLICATION', {})
        self.app_name = vcap_app.get('name', None)
        self._log.debug("App Name [%s]", self.app_name)

        if 'DYNATRACE_SERVER' in self._ctx.keys():
            if self._detected:
                self._log.warn("Detected a Dynatrace Service & Server host,"
                               " using the manual information.")
            self.server = self._ctx['DYNATRACE_SERVER']
            self._detected = True

        if self._detected:
            self.dynatrace_so = os.path.join('@{HOME}', 'dynatrace',
                                            'agent', 'lib64',
                                            'libdtagent.so')
            self._log.debug("PHP Extension [%s]", self.dynatrace_so)

    def _load_php_info(self):
        self.php_ini_path = os.path.join(self._ctx['BUILD_DIR'],
                                         'php', 'etc', 'php.ini')
        self._php_extn_dir = self._find_php_extn_dir()
        self._php_api, self._php_zts = self._parse_php_api()
        self._php_arch = self._ctx.get('DYNATRACE_ARCH', 'x64')
        self._log.debug("PHP API [%s] Arch [%s]",
                        self._php_api, self._php_arch)

    def _load_httpd_info(self):
         self.httpd_conf_path = os.path.join(self._ctx['BUILD_DIR'], 'httpd','conf','httpd.conf')

    def _load_dtwsagent_ini_info(self):
         self.dtwsagent_ini_path =  os.path.join(self._ctx['BUILD_DIR'], 'dynatrace',
                                            'agent', 'conf',
                                            'dtwsagent.ini')
         _log.debug('The following file will be used to configure dt ws agent %s' % self.dtwsagent_ini_path)

    def _find_php_extn_dir(self):
        with open(self.php_ini_path, 'rt') as php_ini:
            for line in php_ini.readlines():
                if line.startswith('extension_dir'):
                    (key, val) = line.strip().split(' = ')
                    return val.strip('"')

    def _parse_php_api(self):
        tmp = os.path.basename(self._php_extn_dir)
        php_api = tmp.split('-')[-1]
        php_zts = (tmp.find('non-zts') == -1)
        return php_api, php_zts

    def should_install(self):
        return self._detected

    def modify_php_ini(self):
        with open(self.php_ini_path, 'rt') as php_ini:
            lines = php_ini.readlines()
        extns = [line for line in lines if line.startswith('extension=')]
        if len(extns) > 0:
            pos = lines.index(extns[-1]) + 1
        else:
            pos = lines.index('#{PHP_EXTENSIONS}\n') + 1
        _log.debug('add extension=%s to php.ini' % self.dynatrace_so)
        lines.insert(pos, 'extension=%s\n' % self.dynatrace_so)
        with open(self.php_ini_path, 'wt') as php_ini:
            for line in lines:
                php_ini.write(line)

    def modify_httpd_conf(self):
        with open(self.httpd_conf_path, 'rt') as httpd_conf:
            lines = httpd_conf.readlines()
        _log.debug('add LoadModule dtagent_module %s to httpd.conf' % self.dynatrace_so)    	
        lines.append('\n')
        lines.append('LoadModule dtagent_module %s\n' % self.dynatrace_so)
        with open(self.httpd_conf_path, 'wt') as httpd_conf:
            for line in lines:
         	     httpd_conf.write(line)

    def modify_dtwsagent_ini(self):
        _log.debug('write ws agent config to %s' % self.dtwsagent_ini_path)
        lines=[]
        lines.append('Name %s_dtwsagent\n' % self.app_name)
        lines.append('Server %s\n' % self.server)
        lines.append('#LogfilePath /path/to/the/logfiles\n')
        lines.append('#SharedMemoryFileName /path/to/dynaTraceWebServerSharedMemory\n')
        lines.append('#SharedMemoryHeapSize 4 MiB\n')
        lines.append('#RemoveTag false\n')
        lines.append('CompressInjectedResponse true\n')
        lines.append('#Storage /path/to/agent/storage\n')
        lines.append('#NoBootstrap false\n')
        lines.append('#UDPQueueLowWatermark 2000\n')
        lines.append('#UDPQueueHighWatermark 50000\n')
        lines.append('isMasterAgentServiceInstalled true\n')
        with open(self.dtwsagent_ini_path, 'w+') as dtwsagent_ini:
            for line in lines:
                dtwsagent_ini.write(line)

# Extension Methods
def preprocess_commands(ctx):
    return ()

def service_commands(ctx):
    _detected = False
    services = ctx.get('VCAP_SERVICES', {})
    service_defs = services.get('dynatrace', [])
    if len(service_defs) == 0:
         service_defs= services.get('user-provided', [])
    if len(service_defs) > 1:
         _log.info("Multiple Dynatrace services defined, will use first one")
    if len(service_defs) > 0:
         service = service_defs[0]
         creds = service.get('credentials', {})
         server = creds.get('server', None)
         _log.info("Service Defined Dynatrace Server %s" % server)
         _detected = True
    if 'DYNATRACE_SERVER' in ctx.keys():
         if _detected:
         	 _log.info("Manually defined Dynatrace server found, using manual info")
         server = ctx['DYNATRACE_SERVER']
         _log.debug("Manually Defined Dynatrace Server: %s" % server)
         _detected = True
    if _detected:
         _log.info("Dynatrace installed, running Dynatrace Webserver Agent")
         return {
             'dynatrace_webserver_agent': ('${HOME}/dynatrace/agent/lib64/dtwsagent',)
         }
    else:
         _log.info("Dynatrace not installed, will not run Webserver Agent")
         return {}    


def service_environment(ctx):
    return {}


def compile(install):
    dynatrace = DynatraceInstaller(install.builder._ctx)
    if dynatrace.should_install():
        _log.info("Installing Dynatrace")
        install.package('DYNATRACE')
        _log.info("Configuring Dynatrace in php.ini")
        dynatrace.modify_php_ini()
        _log.info("Configuring Dynatrace in httpd.conf")
        dynatrace.modify_httpd_conf()
        _log.info("Configuring Dynatrace WebServer Agent ini file")
        dynatrace.modify_dtwsagent_ini()
        _log.info("Dynatrace Installed.")
    return 0
