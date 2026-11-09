export const MAX_UPLOAD_BYTES = 68 * 1024 * 1024;

export async function snapshotUploadFile(selected: File, maximum = MAX_UPLOAD_BYTES): Promise<File> {
  if (selected.size > maximum) throw new Error(`发布包不能超过 ${maximum / 1024 / 1024} MiB。`);
  try {
    // 立即复制字节，避免文件选择器的临时文件在点击提交前失效。
    const bytes = await selected.arrayBuffer();
    return new File([bytes], selected.name, { type: selected.type, lastModified: selected.lastModified });
  } catch {
    throw new Error('无法读取所选文件，请重新选择');
  }
}
