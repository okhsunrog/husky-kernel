/* Exercise the production cursor/actor implementation with controlled filesystem IO. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <limits.h>
#include <errno.h>
#include <unistd.h>

typedef int64_t loff_t;
typedef uint64_t u64;
#define NAME_MAX 255
#define MAX_LFS_FILESIZE INT64_MAX
#define ZEROMOUNT_MAGIC_POS INT64_C(0x7000000000000000)
#define container_of(p, t, m) ((t *)((char *)(p) - offsetof(t, m)))
struct dir_context {
    bool (*actor)(struct dir_context *, const char *, int, loff_t, u64, unsigned int);
    loff_t pos;
};
struct file;
struct file_operations {
    int (*iterate)(struct file *, struct dir_context *);
    int (*iterate_shared)(struct file *, struct dir_context *);
    loff_t (*llseek)(struct file *, loff_t, int);
};
struct file {
    struct file_operations *f_op;
    loff_t f_pos, f_zeromount_cookie, f_zeromount_real_pos;
};
struct { unsigned int val; } uid;
#define current_uid() uid
#define current NULL
static bool compat, disabled, blocked, interrupted, filter;
static bool signal_pending(void *p) { (void)p; return interrupted; }
static bool in_compat_syscall(void) { return compat; }
static bool zeromount_should_skip(void) { return disabled; }
static bool zeromount_is_uid_blocked(unsigned int u) { (void)u; return blocked; }
static bool dir_emit(struct dir_context *c, const char *n, int l, u64 i, unsigned int t)
{ return c->actor(c, n, l, c->pos, i, t); }
static loff_t vfs_setpos(struct file *f, loff_t o, loff_t max)
{ if(o < 0 || o > max) return -EINVAL; f->f_pos = o; return o; }
static unsigned int virtual_count = 3;
static bool zeromount_dir_child(struct file *f, unsigned long index, char *name,
                               unsigned long *ino, unsigned int *type)
{
    (void)f;
    if(index >= virtual_count) return false;
    snprintf(name, NAME_MAX+1, "virtual-%lu", index);
    *ino = 100+index; *type = 8; return true;
}

#include "zeromount_readdir.c"

static loff_t native_eof;
static unsigned int native_calls;
static bool native_error;
static int native_iterate(struct file *f, struct dir_context *c)
{
    (void)f;
    native_calls++;
    if(native_error) return -EIO;
    if(c->pos == native_eof) return 0;
    for(; c->pos < 3; c->pos++) {
        char name[32]; snprintf(name, sizeof(name), "native-%lld", (long long)c->pos);
        if(!dir_emit(c, name, strlen(name), c->pos+1, 8)) return 0;
    }
    c->pos = native_eof;
    return 0;
}
static loff_t native_seek(struct file *f, loff_t o, int whence)
{
    if(whence == SEEK_END) o += native_eof;
    if(whence == SEEK_CUR) o += f->f_pos;
    return vfs_setpos(f, o, INT64_MAX);
}
static struct file_operations ops = { native_iterate, native_iterate, native_seek };
struct output {
    struct dir_context ctx;
    unsigned int capacity, used;
    bool fault;
    char names[16][32];
    loff_t offsets[16];
};
static bool collect(struct dir_context *c, const char *n, int l, loff_t off, u64 ino, unsigned int t)
{
    (void)ino; (void)t;
    struct output *out = container_of(c, struct output, ctx);
    /* A wrapper like vpnhide can consume a hidden entry without writing it. */
    if(filter && (strcmp(n,"native-1")==0 || strcmp(n,"virtual-1")==0)) return true;
    if(out->fault || out->used == out->capacity) return false;
    assert(l < 32 && out->used < 16);
    memcpy(out->names[out->used], n, l+1);
    out->offsets[out->used++] = off;
    return true;
}
static struct output read_dir(struct file *f, unsigned int size, bool shared, bool fault)
{
    struct output out = { .ctx.actor = collect, .ctx.pos = f->f_pos,
                          .capacity = size, .fault = fault };
    int rc = zeromount_iterate_dir(f, &out.ctx, shared);
    assert(rc == (native_error ? -EIO : 0));
    f->f_pos = out.ctx.pos;
    return out;
}
static void reset(void)
{
    compat = disabled = blocked = interrupted = native_error = filter = false;
    native_calls = 0; native_eof = INT64_MAX; virtual_count = 3;
}
static void enumerate(loff_t eof, unsigned int size, bool is_compat, bool shared)
{
    reset(); compat = is_compat; native_eof = eof;
    struct file f = { .f_op = &ops };
    unsigned int count = 0;
    for(unsigned int pass = 0; pass < 16; pass++) {
        struct output out = read_dir(&f, size, shared, false);
        for(unsigned int i=0;i<out.used;i++,count++) {
            char expected[32];
            snprintf(expected,sizeof(expected),"%s-%u",count<3?"native":"virtual",count%3);
            assert(strcmp(out.names[i],expected)==0);
            if(count >= 3) assert(out.offsets[i] == (is_compat ? INT64_C(0x70000000) : ZEROMOUNT_MAGIC_POS) + count-3);
        }
        if(!out.used) break;
    }
    assert(count == 6);
    unsigned int calls = native_calls;
    assert(read_dir(&f,size,shared,false).used == 0);
    assert(native_calls == calls);
    assert(zeromount_dir_llseek(&f,0,SEEK_CUR)==f.f_pos);
    assert(zeromount_dir_llseek(&f,-1,SEEK_SET)==-EINVAL);
    assert(f.f_zeromount_cookie!=0);
    loff_t base = is_compat ? INT64_C(0x70000000) : ZEROMOUNT_MAGIC_POS;
    assert(zeromount_dir_llseek(&f,base+1,SEEK_SET)==base+1);
    struct output out = read_dir(&f,8,shared,false);
    assert(out.used==2 && strcmp(out.names[0],"virtual-1")==0);
    assert(native_calls==calls);
    assert(zeromount_dir_llseek(&f,0,SEEK_SET)==0);
    assert(f.f_zeromount_cookie==0);
    out=read_dir(&f,8,shared,false);
    assert(out.used==3 && strcmp(out.names[0],"native-0")==0);
}
int main(void)
{
    for(unsigned int size=1;size<=8;size++) {
        enumerate(INT64_MAX,size,false,true); /* ext4 htree 64-bit EOF */
        enumerate(INT32_MAX,size,true,false); /* compat/32-bit cookie */
        enumerate(4096,size,false,false);     /* linear directory EOF */
    }
    reset(); struct file f={.f_op=&ops};
    virtual_count=0;
    assert(read_dir(&f,8,true,false).used==3);
    assert(read_dir(&f,8,true,false).used==0 && f.f_zeromount_cookie==0);
    reset(); f=(struct file){.f_op=&ops};
    assert(read_dir(&f,0,true,false).used==0 && f.f_pos==0);
    assert(read_dir(&f,8,true,false).used==3);
    assert(read_dir(&f,0,true,false).used==0 && f.f_zeromount_cookie==ZEROMOUNT_MAGIC_POS);
    assert(read_dir(&f,8,true,false).used==3);
    reset(); f=(struct file){.f_op=&ops};
    assert(read_dir(&f,8,true,true).used==0 && f.f_pos==0);
    assert(read_dir(&f,8,true,false).used==3);
    assert(read_dir(&f,8,true,true).used==0 && f.f_pos==ZEROMOUNT_MAGIC_POS);
    assert(read_dir(&f,8,true,false).used==3);
    reset(); f=(struct file){.f_op=&ops};
    read_dir(&f,8,true,false); read_dir(&f,1,true,false);
    disabled=true;
    assert(read_dir(&f,8,true,false).used==0 && f.f_pos==INT64_MAX && f.f_zeromount_cookie==0);
    reset(); f=(struct file){.f_op=&ops}; blocked=true;
    read_dir(&f,8,true,false);
    assert(read_dir(&f,8,true,false).used==0 && f.f_zeromount_cookie==0);
    reset(); f=(struct file){.f_op=&ops}; native_error=true;
    assert(read_dir(&f,8,true,false).used==0 && f.f_zeromount_cookie==0);
    reset(); f=(struct file){.f_op=&ops};
    read_dir(&f,8,true,false); interrupted=true;
    assert(read_dir(&f,8,true,false).used==0 && f.f_zeromount_cookie==0);
    interrupted=false;
    assert(read_dir(&f,8,true,false).used==3);
    /* A large *native* cookie without per-open virtual state stays native. */
    reset(); f=(struct file){.f_op=&ops,.f_pos=ZEROMOUNT_MAGIC_POS+1};
    assert(read_dir(&f,8,true,false).used==3 && native_calls==1);
    reset(); f=(struct file){.f_op=&ops}; filter=true;
    struct output out=read_dir(&f,8,true,false);
    assert(out.used==2 && strcmp(out.names[1],"native-2")==0);
    out=read_dir(&f,8,true,false);
    assert(out.used==2 && strcmp(out.names[1],"virtual-2")==0);
    assert(read_dir(&f,8,true,false).used==0);
    puts("directory cursor/actor regression tests passed");
}
