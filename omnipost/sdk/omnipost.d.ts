export interface OmniPostOptions {
  baseUrl?: string;
  apiKey?: string;
  timeout?: number;
}

export interface PublishParams {
  title?: string;
  caption: string;
  mediaUrl?: string;
  mediaType?: 'video' | 'image' | 'text';
  platforms?: string[] | string;
  link?: string;
}

export interface ScheduleParams extends PublishParams {
  scheduledDateTime: string | Date;
}

export interface PublishResult {
  success: boolean;
  contentId: string;
  status: string;
  results: Array<{
    platform: string;
    status: string;
    permalink?: string | null;
    error?: string | null;
  }>;
  summary?: {
    published: number;
    failed: number;
    skipped: number;
    requested: number;
  };
}

export interface StatusResult {
  success: boolean;
  contentId: string;
  status: string;
  publishState: string;
  platformStatuses: Record<string, any>;
  platforms: string;
  title: string;
}

export declare class OmniPostError extends Error {
  status: number;
  code: string;
  details: any;
  constructor(message: string, options?: { status?: number; code?: string; details?: any });
}

export declare class OmniPost {
  baseUrl: string;
  apiKey: string;
  timeout: number;

  constructor(options?: OmniPostOptions);

  preflight(): Promise<{
    signal: string;
    armed: boolean;
    selectiveArmed: boolean;
    readyToPublish: string[];
    channels: Record<string, any>;
  }>;

  getChannels(): Promise<{
    channels: Array<{
      id: string;
      name: string;
      configured: boolean;
      missingKeys: string[];
    }>;
  }>;

  publish(params: PublishParams): Promise<PublishResult>;

  schedule(params: ScheduleParams): Promise<{
    success: boolean;
    contentId: string;
    scheduledDateTime: string;
  }>;

  getStatus(contentId: string): Promise<StatusResult>;

  getPosts(): Promise<{ count: number; posts: any[] }>;

  uploadMedia(
    fileData: any,
    filename?: string,
    metadata?: Partial<ScheduleParams> & { status?: string }
  ): Promise<{
    success: boolean;
    contentId: string;
    publicMediaUrl: string;
    mediaType: string;
  }>;
}

export default OmniPost;
