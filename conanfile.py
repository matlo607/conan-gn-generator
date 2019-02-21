from conans import ConanFile, tools
from conans.client.output import ConanOutput
from conans.model import Generator

from functools import wraps
import io
import sys
import textwrap


##################
# Local indenter #
##################

def prepend_2s(s):
    return textwrap.indent(s, prefix=' ' * 2)


def prepender(s_function):
    @wraps(s_function)
    def wrapped_s_function(*args, **kwargs):
        args = list(args)
        prepended_s = prepend_2s(args[0])
        args = tuple([prepended_s] + args[1:])
        return s_function(*args, **kwargs)
    return wrapped_s_function


class StringIOClsWrapper(object):

    def __init__(self, instance, wrapped_funcs):
        self._instance = instance
        self._wrapped_funcs = wrapped_funcs

    def __getattribute__(self, name):
        try:
            attr = super(StringIOClsWrapper, self).__getattribute__(name)
        except AttributeError:
            pass
        else:
            return attr

        attr = self._instance.__getattribute__(name)
        if attr.__name__ in self._wrapped_funcs.keys():
            return self._wrapped_funcs[attr.__name__](attr)
        else:
            return attr


class StringIO_wrapper(object):

    def __init__(self, instance, write_method):
        self._instance = instance
        self._write_method = write_method

    def __enter__(self):
        return StringIOClsWrapper(self._instance, {"write": self._write_method})

    def __exit__(self, *args, **kwargs):
        pass


##############
# GN Grammar #
##############

class GNIdentifier(object):
    def __init__(self, name):
        self._name = name

    def __str__(self):
        return self._name


class GNBool(object):
    def __init__(self, value):
        self._b = value

    def __str__(self):
        return self._b.__str__().lower()


class GNString(str):
    def __str__(self):
        return'"' + super().__str__() + '"'


class GNList(list):
    def __str__(self):
        if len(self) == 0:
            return "[]"
        else:
            output = io.StringIO()
            if len(self) > 3:
                output.write('[\n')
                with StringIO_wrapper(output, prepender) as output_:
                    output_.write(',\n'.join(map(str, self)))
                output.write('\n]')
            else:
                output.write('[ ')
                output.write(', '.join(map(str, self)))
                output.write(' ]')
            return output.getvalue()


class GNScope(dict):
    def __str__(self):
        if len(self) == 0:
            return "{}"
        else:
            output = io.StringIO()
            output.write("{\n")
            with StringIO_wrapper(output, prepender) as output_:
                for key, value in self.items():
                    output_.write("{key} = {value},\n".format(key=key, value=str(value)))
            output.write("}")
            return output.getvalue()


class GNVarStatement(object):
    def __init__(self, name, value):
        self._name = name
        self._value = value

    def __str__(self):
        return "{name} = {value}".format(name=self._name, value=str(self._value))


class GNCallStatement(object):
    def __init__(self, name, parameters=None, block=None):
        self._name = name
        self._parameters = parameters
        self._block = block

    def __str__(self):
        output = io.StringIO()
        output.write("{name}(".format(name=self._name))
        if self._parameters:
            output.write(', '.join(map(str, self._parameters)))
        output.write(")")
        if self._block:
            output.write(" {\n")
            with StringIO_wrapper(output, prepender) as output_:
                output_.write('\n'.join(map(str, self._block)))
            output.write("\n}")
        return output.getvalue()


#############
# Generator #
#############

class GNGenerator(Generator):

    _output = ConanOutput(sys.stdout, True)

    def _get_gn_file_content(self, dep_name, dep_cpp_info):

        configs = list()

        tree = list()
        #tree.append(GNVarStatement("_root", GNString(dep_cpp_info.rootpath)))

        config_name = "{dep_name}_include".format(dep_name=dep_name)
        visibility = "include"
        configs.append(tuple([config_name, visibility]))

        tree.append(GNCallStatement(name="config",
                                    parameters=[GNString(config_name)],
                                    block=[
                                      GNVarStatement("include_dirs",
                                                     GNList(
                                                        [GNString(include_path)
                                                         for include_path in dep_cpp_info.include_paths])),
                                      GNVarStatement("defines",
                                                     GNList(
                                                        [GNString(flag)
                                                         for flag in dep_cpp_info.defines])),
                                      GNVarStatement("cflags_c",
                                                     GNList(
                                                        [GNString(flag)
                                                         for flag in dep_cpp_info.cflags])),
                                      GNVarStatement("cflags_cc",
                                                     GNList(
                                                        [GNString(flag)
                                                         for flag in dep_cpp_info.cppflags])),
                                      GNVarStatement("visibility",
                                                     GNList([GNString(":{}".format(visibility))]))
                                    ]))

        config_name = "{dep_name}_runtime_path".format(dep_name=dep_name)
        visibility = "runtime_path"
        configs.append(tuple([config_name, visibility]))
        tree.append(GNCallStatement(name="config",
                                    parameters=[GNString(config_name)],
                                    block=[
                                      GNVarStatement("lib_dirs",
                                                     GNList([GNString(lib_path)
                                                             for lib_path in dep_cpp_info.lib_paths])),
                                      GNVarStatement("ldflags",
                                                     GNList(
                                                        [GNString(flag)
                                                         for flag in dep_cpp_info.sharedlinkflags] +
                                                        [GNString(flag)
                                                         for flag in dep_cpp_info.exelinkflags])),
                                      GNVarStatement("visibility",
                                                     GNList([GNString(":{}".format(visibility))]))
                                    ]))

        for lib_name in dep_cpp_info.libs:
            config_name = "{}_lib_{}".format(dep_name, lib_name)
            configs.append(tuple([config_name, lib_name]))
            tree.append(GNCallStatement(name="config",
                                        parameters=[GNString(config_name)],
                                        block=[
                                          GNVarStatement("libs",
                                                         GNList([GNString(lib_name)])),
                                          GNVarStatement("visibility",
                                                         GNList([GNString(":{}".format(lib_name))]))
                                        ]))

        for config_name, visibility in configs:
            tree.append(GNCallStatement(name="group",
                                        parameters=[GNString(visibility)],
                                        block=[
                                          GNVarStatement("public_configs",
                                                         GNList([GNString(":{}".format(config_name))]))
                                        ]))

        return '\n\n'.join(map(str, tree)) + '\n'

    @property
    def filename(self):
        #root_build_thirdparty = os.path.join("thirdparty", "conan")
        #tools.mkdir(root_build_thirdparty)
        #with tools.chdir(root_build_thirdparty):
        for dep_name, dep_cpp_info in self.deps_build_info.dependencies:
            tools.mkdir(dep_name)
            with tools.chdir(dep_name):
                with open("BUILD.gn", "w") as fd:
                    fd.write(self._get_gn_file_content(dep_name, dep_cpp_info))
        return "BUILD.gn"

    @property
    def content(self):
        return "# All the files in the subdirectories are generated using Conan\n" + \
               "# Licence: {}\n".format(GNGeneratorConanFile.licence) + \
               "conan_gn_generator_version = \"{}\"\n".format(GNGeneratorConanFile.version)

class GNGeneratorConanFile(ConanFile):
    name = "GNGenerator"
    version = "0.1"
    url = "https://github.com/matlo607/conan-gn-generator.git"
    licence = "MIT License (https://github.com/matlo607/conan-gn-generator/blob/master/LICENSE)"
    exports = "*.py"
    settings = "os", "compiler", "build_type", "arch"

    def build(self):
        pass

    def package_info(self):
        pass
