# This file is part of the MapProxy project.
# Copyright (C) 2011 Omniscale <http://omniscale.de>
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import with_statement
import os
import optparse
import re
import shutil
import sys
import textwrap

from mapproxy.version import version

def setup_logging():
    import logging
    imposm_log = logging.getLogger('mapproxy')
    imposm_log.setLevel(logging.INFO)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "[%(asctime)s] %(name)s - %(levelname)s - %(message)s")
    ch.setFormatter(formatter)
    imposm_log.addHandler(ch)

def serve_develop_command(args):
    parser = optparse.OptionParser("usage: %prog serve-develop [options] mapproxy.yaml")
    parser.add_option("-b", "--bind",
                      dest="address", default='127.0.0.1:8080',
                      help="Server socket [127.0.0.1:8080]")
    parser.add_option("--debug", default=False, action='store_true',
                      dest="debug",
                      help="Enable debug mode")
    options, args = parser.parse_args(args)
    
    if len(args) != 2:
        parser.print_help()
        print "\nERROR: MapProxy configuration required."
        sys.exit(1)
        
    mapproxy_conf = args[1]
    
    host, port = parse_bind_address(options.address)
    
    if options.debug and host not in ('localhost', '127.0.0.1'):
        print textwrap.dedent("""\
        ################# WARNING! ##################
        Running debug mode with non-localhost address
        is a serious security vulnerability.
        #############################################\
        """)
    
    
    setup_logging()
    from mapproxy.wsgiapp import make_wsgi_app
    from mapproxy.config.loader import ConfigurationError
    from mapproxy.util.ext.serving import run_simple
    try:
        app = make_wsgi_app(mapproxy_conf, debug=options.debug)
    except ConfigurationError, ex:
        print "ERROR:\t" + '\n\t'.join(str(ex).split('\n'))
        sys.exit(2)
    
    if options.debug:
        processes = 1
        threaded = False
    else:
        processes = 4
        threaded = False
    run_simple(host, port, app, use_reloader=True, processes=processes,
        threaded=threaded, passthrough_errors=True,
        extra_files=[mapproxy_conf])


def parse_bind_address(address, default=('localhost', 8080)):
    """
    >>> parse_bind_address('80')
    ('localhost', 80)
    >>> parse_bind_address('0.0.0.0')
    ('0.0.0.0', 8080)
    >>> parse_bind_address('0.0.0.0:8081')
    ('0.0.0.0', 8081)
    """
    if ':' in address:
        host, port = address.split(':', 1)
        port = int(port)
    elif re.match('^\d+$', address):
        host = default[0]
        port = int(address)
    else:
        host = address
        port = default[1]
    return host, port


def create_command(args):
    cmd = CreateCommand(args)
    cmd.run()

class CreateCommand(object):
    templates = {
        'base-config': {},
        'wsgi-app': {},
    }
    
    APP_TEMPLATE = textwrap.dedent("""\
    # WSGI module for use with Apache mod_wsgi or gunicorn

    from mapproxy.wsgiapp import make_wsgi_app
    application = make_wsgi_app('%s')
    """)

    def __init__(self, args):
        parser = optparse.OptionParser("usage: %prog create [options] [destination]")
        parser.add_option("-t", "--template", dest="template",
            help="Create a configuration from this template.")
        parser.add_option("-l", "--list-templates", dest="list_templates",
            action="store_true", default=False,
            help="List all available configuration templates.")
        parser.add_option("-f", "--mapproxy-conf", dest="mapproxy_conf",
            help="Existing MapProxy configuration (required for some templates).")
        parser.add_option("--force", dest="force", action="store_true",
            default=False, help="Force operation (e.g. overwrite existing files).")

        self.options, self.args = parser.parse_args(args)
        self.parser = parser

    def log_error(self, msg, *args):
        print >>sys.stderr, 'ERROR:', msg % args
        
    def run(self):
        
        if self.options.list_templates:
            print_items(self.templates, title="Available templates")
            sys.exit(1)
        elif self.options.template:
            if self.options.template not in self.templates:
                self.log_error("unknown template " + self.options.template)
                sys.exit(1)
            
            if len(self.args) != 2:
                self.log_error("template requires destination argument")
                sys.exit(1)
                
            sys.exit(
                getattr(self, 'template_' + self.options.template.replace('-', '_'))()
            )
        else:
            self.parser.print_help()
            sys.exit(1)

    @property
    def mapproxy_conf(self):
        if not self.options.mapproxy_conf:
            self.parser.print_help()
            self.log_error("template requires --mapproxy-conf option")
            sys.exit(1)
        return os.path.abspath(self.options.mapproxy_conf)
    
    def template_wsgi_app(self):
        app_filename = self.args[1]
        if '.' not in os.path.basename(app_filename):
            app_filename += '.py'
        mapproxy_conf = self.mapproxy_conf
        if os.path.exists(app_filename) and not self.options.force:
            self.log_error("%s already exists, use --force", app_filename)
            return 1

        print "writing MapProxy app to %s" % (app_filename, )
        with open(app_filename, 'w') as f:
            f.write(self.APP_TEMPLATE % (mapproxy_conf, ))
        
        return 0
    
    def template_base_config(self):
        outdir = self.args[1]
        if not os.path.exists(outdir):
            os.makedirs(outdir)
        
        import mapproxy.config_template
        template_dir = os.path.join(
            os.path.dirname(mapproxy.config_template.__file__),
            'base_config')
        
        for filename in ('mapproxy.yaml', 'seed.yaml'):
            to = os.path.join(outdir, filename)
            from_ = os.path.join(template_dir, filename)
            if os.path.exists(to) and not self.options.force:
                self.log_error("%s already exists, use --force", to)
                return 1
            print "writing %s" % (to, )
            shutil.copy(from_, to)
            
commands = {
    'serve-develop': {
        'func': serve_develop_command,
        'help': 'Run MapProxy development server.'
    },
    'create': {
        'func': create_command,
        'help': 'Create example configurations.'
    },
}


class NonStrictOptionParser(optparse.OptionParser):
    def _process_args(self, largs, rargs, values):
        while rargs:
            arg = rargs[0]
            # We handle bare "--" explicitly, and bare "-" is handled by the
            # standard arg handler since the short arg case ensures that the
            # len of the opt string is greater than 1.
            try:
                if arg == "--":
                    del rargs[0]
                    return
                elif arg[0:2] == "--":
                    # process a single long option (possibly with value(s))
                    self._process_long_opt(rargs, values)
                elif arg[:1] == "-" and len(arg) > 1:
                    # process a cluster of short options (possibly with
                    # value(s) for the last one only)
                    self._process_short_opts(rargs, values)
                elif self.allow_interspersed_args:
                    largs.append(arg)
                    del rargs[0]
                else:
                    return
            except optparse.BadOptionError:
                largs.append(arg)
    

def print_items(data, title='Commands'):
    name_len = max(len(name) for name in data)
    
    if title:
        print >>sys.stdout, '%s:' % (title, )
    for name, item in data.iteritems():
        help = item.get('help', '')
        name = ('%%-%ds' % name_len) % name
        if help:
            help = '  ' + help
        print >>sys.stdout, '  %s%s' % (name, help)

def main():
    parser = NonStrictOptionParser("usage: %prog COMMAND [options]",
        version='MapProxy ' + version, add_help_option=False)
    options, args = parser.parse_args()
    
    if len(args) < 1 or args[0] in ('--help', '-h'):
        parser.print_help()
        print
        print_items(commands)
        sys.exit(1)
        
    command = args[0]
    if command not in commands:
        parser.print_help()
        print
        print_items(commands)
        print >>sys.stdout, '\nERROR: unknown command %s' % (command,)
        sys.exit(1)
    
    args = sys.argv[0:1] + sys.argv[2:]
    commands[command]['func'](args)
    
if __name__ == '__main__':
    main()