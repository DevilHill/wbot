"""WBot 编码版入门：安装 wbot 后直接运行，无需浏览器或元素库。"""
from wbot import logging, strings


def main():
    logging.configure()
    message = "你好，WBot"
    # 在下一行左侧设置断点，单步执行后查看 message 的变化。
    message = strings.replace(message, "你好", "您好")
    logging.info(message)
    return message


if __name__ == "__main__":
    main()
