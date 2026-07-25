import { describe, expect, it } from 'vitest';
import access from './access';

describe('access', () => {
  it('should return canAdmin true when user has admin role', () => {
    const initialState = {
      currentUser: {
        id: 1,
        username: 'admin',
        role: 'admin',
      },
    };

    const result = access(initialState);

    expect(result.canAdmin).toBe(true);
  });

  it('should return canAdmin false when user has non-admin role', () => {
    const initialState = {
      currentUser: {
        id: 2,
        username: 'user',
        role: 'user',
      },
    };

    const result = access(initialState);

    expect(result.canAdmin).toBe(false);
  });

  it('should return canAdmin false when currentUser is undefined', () => {
    const initialState = {
      currentUser: undefined,
    };

    const result = access(initialState);

    expect(result.canAdmin).toBeFalsy();
  });

  it('should return canAdmin false when initialState is undefined', () => {
    const result = access(undefined);

    expect(result.canAdmin).toBeFalsy();
  });
});
