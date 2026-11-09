import { errorMessage, request } from './api';
import type { ElementCommit, ElementMergeRequest, ElementRepository, ElementRepositoryDetail, ElementResolution, ElementReview } from './element-types';

const repositoriesPath = '/elements/repositories';
const repositoryPath = (id: string) => `${repositoriesPath}/${encodeURIComponent(id)}`;
const mergeRequestPath = (repositoryId: string, id: string) => `${repositoryPath(repositoryId)}/requests/${encodeURIComponent(id)}`;

export function elementErrorMessage(error: unknown) {
  if (error instanceof Error && error.name === 'TimeoutError') return '操作响应超时。服务器可能已经保存结果，请刷新仓库或审阅状态核对后重试。';
  return errorMessage(error);
}

export const readElementRepositories = () => request<{ items: ElementRepository[] }>(repositoriesPath);
export const readElementRepository = (id: string) => request<ElementRepositoryDetail>(repositoryPath(id));
export const readElementCommit = (repositoryId: string, id: string) => request<{ commit: ElementCommit }>(`${repositoryPath(repositoryId)}/commits/${encodeURIComponent(id)}`);
export const readElementReview = (repositoryId: string, id: string) => request<ElementReview>(mergeRequestPath(repositoryId, id));

export function createElementRepository(body: { name: string; description: string; request_id: string }) {
  return request<{ repository: ElementRepository }>(repositoriesPath, { body });
}
export function mergeElements(repositoryId: string, id: string, body: { expected_main: string; expected_source: string; resolutions: ElementResolution[]; request_id: string }) {
  return request<{ request: ElementMergeRequest; commit: ElementCommit }>(`${mergeRequestPath(repositoryId, id)}/merge`, { body });
}
export function closeElementRequest(repositoryId: string, id: string, body: { expected_source: string; reason: string; request_id: string }) {
  return request<{ request: ElementMergeRequest }>(`${mergeRequestPath(repositoryId, id)}/close`, { body });
}
export function restoreElements(repositoryId: string, body: { expected_head: string; commit_id: string; message: string; request_id: string }) {
  return request<{ commit: ElementCommit }>(`${repositoryPath(repositoryId)}/restore`, { body });
}
