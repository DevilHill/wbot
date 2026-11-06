from wbot import runtime

parameters = runtime.parameters()
message = f"你好，{parameters['name']}"
print(message)
runtime.set_result({"message": message})
