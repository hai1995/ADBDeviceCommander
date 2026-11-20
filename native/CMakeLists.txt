# adc_mf_sink —— 同源录屏 native 扩展（Windows x64 / MSVC）
# 构建产物 adc_mf_sink.dll 放进 Python 包，由 backend/mf_native.py 用 ctypes 加载。
#
# 用法（在 native/ 下）：
#   cmake -S . -B build -A x64
#   cmake --build build --config Release
#   cmake --install build --prefix ..\backend      # 产出 backend\adc_mf_sink.dll
#
# 无第三方依赖：只链接 Windows 系统库。MSVC 的 C++ 运行时静态链接（/MT），
# 避免分发时另行携带 vcruntime DLL；若选择 /MD 需在打包时带上对应 redist。

cmake_minimum_required(VERSION 3.20)
project(adc_mf_sink LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_definitions(-DUNICODE -D_UNICODE -DADC_MF_SINK_EXPORTS -D_WIN32_WINNT=0x0A00)

add_library(adc_mf_sink SHARED adc_mf_sink.cpp adc_mf_sink.h)

# 静态链接 CRT：包体只多几十 KB，省去 vcredist 依赖。
foreach(flag CMAKE_CXX_FLAGS_RELEASE CMAKE_CXX_FLAGS_DEBUG)
  string(REPLACE "/MD" "/MT" ${flag} "${${flag}}")
endforeach()

target_link_libraries(adc_mf_sink PRIVATE
  mfplat.lib mfreadwrite.lib mfuuid.lib
  ole32.lib propsys.lib uuid.lib advapi32.lib)

set_target_properties(adc_mf_sink PROPERTIES
  OUTPUT_NAME "adc_mf_sink"
  PREFIX "")

install(TARGETS adc_mf_sink RUNTIME DESTINATION .)
