from fastai.basics import *
from ..music_transformer.transform import *
from ..music_transformer.dataloader import MusicDataBunch, MusicItemList
# Sequence 2 Sequence Translate

class MultitrackItem():
    def __init__(self, melody:MusicItem, chords:MusicItem, stream=None):
        self.melody,self.chords = melody, chords
        self.vocab = melody.vocab
        self._stream = stream
        
    @classmethod
    def from_file(cls, midi_file, vocab):
        stream = file2stream(midi_file)
        num_parts = len(stream.parts)
        if num_parts > 2: 
            raise ValueError('Could not extract melody and chords from midi file. Please make sure file contains exactly 2 tracks')
        elif num_parts == 1: 
            print('Warning: only 1 track found. Inferring melody/chords')
            stream = separate_melody_chord(stream)
            
        mpart, cpart = stream2npenc_parts(stream)
        return cls.from_npenc_parts(mpart, cpart, vocab)
        
    @classmethod
    def from_npenc_parts(cls, mpart, cpart, vocab):
        mpart = npenc2idxenc(mpart, seq_type=SEQType.Melody, vocab=vocab, add_eos=True)
        cpart = npenc2idxenc(cpart, seq_type=SEQType.Chords, vocab=vocab, add_eos=True)
        return MultitrackItem(MusicItem(mpart, vocab), MusicItem(cpart, vocab))
        
    @classmethod
    def from_idx(cls, item, vocab):
        m, c = item
        return MultitrackItem(MusicItem.from_idx(m, vocab), MusicItem.from_idx(c, vocab))
    def to_idx(self): return np.array((self.melody.to_idx(), self.chords.to_idx()))
    
    @property
    def stream(self, bpm=120):
        if self._stream is None:
            ps = self.melody.to_npenc(), self.chords.to_npenc()
            ps = [npenc2chordarr(p) for p in ps]
            chordarr = chordarr_combine_parts(ps)
            self._stream = chordarr2stream(chordarr)
        return self._stream
    
    def show(self, format:str=None):
        return self.stream.show(format)
    def play(self): self.stream.show('midi')
        
    def transpose(self, val):
        return MultitrackItem(self.melody.transpose(val), self.chords.transpose(val))
    def pad_to(self, val):
        return MultitrackItem(self.melody.pad_to(val), self.chords.pad_to(val))
    

class S2SFileProcessor(PreProcessor):
    "`PreProcessor` that opens the filenames and read the texts."
    def process_one(self,item):
        out = np.load(item, allow_pickle=True)
        if out.shape != (2,): return None
        if not 16 < len(out[0]) < 2048: return None
        if not 16 < len(out[1]) < 2048: return None
        return out
    
    def process(self, ds:Collection):
        ds.items = [self.process_one(item) for item in ds.items]
        ds.items = [i for i in ds.items if i is not None] # filter out None
#         ds.items = array([self.process_one(item) for item in ds.items], dtype=np.object)

class S2SPartsProcessor(PreProcessor):
    "Encodes midi file into 2 separate parts - melody and chords."
    
    def process_one(self, item):
        m, c = item
        mtrack = MultitrackItem.from_npenc_parts(m, c, vocab=self.vocab)
        return mtrack.to_idx()
    
    def process(self, ds):
        self.vocab = ds.vocab
        ds.items = [self.process_one(item) for item in ds.items]
        
class S2SPreloader(Callback):
    def __init__(self, dataset:LabelList, bptt:int=512, 
                 transpose_range=(0,12), **kwargs):
        self.dataset,self.bptt = dataset,bptt
        self.vocab = self.dataset.vocab
        self.rand_transpose = partial(rand_transpose_value, rand_range=transpose_range) if transpose_range is not None else None
        
    def __getitem__(self, k:int):
        item,empty_label = self.dataset[k]
        
        if self.rand_transpose is not None:
            val = self.rand_transpose()
            item = item.transpose(val)
        item = item.pad_to(self.bptt+1)
        ((m_x, m_pos), (c_x, c_pos)) = item.to_idx()
#         m_x = pad_seq(m.data, self.bptt+1, self.vocab.pad_idx)
#         m_pos = pad_seq(m.position, self.bptt+1, 0)
#         c_x = pad_seq(c.data, self.bptt+1, self.vocab.pad_idx)
#         c_pos = pad_seq(c.position, self.bptt+1, 0)
        return m_x, m_pos, c_x, c_pos
#         return {
#             'm': pad_seq(m.data, self.bptt+1, self.vocab.pad_idx),
#             'm_pos': pad_seq(m.position, self.bptt+1, 0),
#             'c': pad_seq(c.data, self.bptt+1, self.vocab.pad_idx),
#             'c_pos': pad_seq(c.position, self.bptt+1, 0),
#         }
        # WARNING: we are padding position encodings too. However, pos is negative, so should be fine
#         return ,  # offset bptt for decoder shift
    
    def __len__(self):
        return len(self.dataset)

def rand_transpose_value(rand_range=(0,24), p=0.5):
    if np.random.rand() < p: return np.random.randint(*rand_range)-rand_range[1]//2
    return 0

class S2SItemList(MusicItemList):
    _bunch = MusicDataBunch
    def get(self, i):
        return MultitrackItem.from_idx(self.items[i], self.vocab)


def pad_seq(seq, bptt, value):
    pad_len = max(bptt-seq.shape[0], 0)
    return np.pad(seq, (0, pad_len), 'constant', constant_values=value)[:bptt]
    
# def pad_seq(seq, bptt, value):
#     pad_len = max(bptt-seq.shape[0], 0)
#     return np.pad(seq, [(0, pad_len),(0,0)], 'constant', constant_values=value)[:bptt]
    
# def partenc2seq2seq(part_np, seq_type, vocab, add_eos=True):
#     s2s_out = npenc2idxenc(part_np, vocab=vocab, seq_type=seq_type)
#     if add_eos: s2s_out = np.pad(s2s_out, (0,1), 'constant', constant_values=vocab.stoi[EOS])
#     return s2s_out

def s2s_combine2chordarr(np1, np2, vocab):
    if len(np1.shape) == 1: np1 = idxenc2npenc(np1, vocab)
    if len(np2.shape) == 1: np2 = idxenc2npenc(np2, vocab)
    p1 = npenc2chordarr(np1)
    p2 = npenc2chordarr(np2)
    return chordarr_combine_parts((p1, p2))

# def midi_extract_melody_chords(midi, vocab):
#     stream = file2stream(midi) # 1.
#     parts = stream2npenc_parts(stream)
#     num_parts = len(parts)

#     if num_parts == 1:
#         # if predicting melody, assume only track is chord track
#         p1, p2 = part_enc(chordarr, 0), np.zeros((0,2), dtype=int)
#         p1, p2 = (p2, p1) if pred_melody else (p1, p2)
#     elif num_parts == 2:
#         p1, p2 = [part_enc(chordarr, i) for i in range(num_parts)]
#         p1, p2 = (p1, p2) if avg_pitch(p1) > avg_pitch(p2) else (p2, p1)
#     else:
#         raise ValueError('Could not extract melody and chords from midi file. Please make sure file contains exactly 2 tracks')
        
#     mpart = partenc2seq2seq(p1, part_type=MSEQ, vocab=vocab)
#     cpart = partenc2seq2seq(p2, part_type=CSEQ, vocab=vocab)
#     return mpart, cpart


# DATALOADING AND TRANSFORMATIONS

# MLMType = Enum('MLMType', 'Mask, NextWord, M2C, C2M')

# MLM Transform - DEPRECATED
def msklm_mask(shape, p, tile):
    p = p / tile # scale probability
    rand_mask = torch.rand(*shape) < p
    if tile > 1:
        rand_mask = torch.repeat_interleave(rand_mask, tile, dim=1)[:rand_mask.shape[0], :rand_mask.shape[1]]
        
    lm_mask = torch.roll(rand_mask, 1, dims=1)
    lm_mask[:, 0] = 0
    lm_mask = rand_mask & lm_mask
    return rand_mask, lm_mask

def mask_tfm(b, vocab, p=0.2):
# def mask_tfm(b, word_range=vocab.npenc_range, pad_idx=vocab.pad_idx, 
#              mask_idx=vocab.mask_idx, p=0.2):
    # p = replacement probability
    word_range = vocab.npenc_range
    x,y = b
    x,y = x.clone(),y.clone()
    rand = torch.rand(x.shape, device=x.device)
    rand[x < word_range[0]] = 1.0
    rand[x >= word_range[1]] = 1.0
    y[rand > p] = vocab.pad_idx
    x[rand <= (p*.8)] = vocab.mask_idx # 80% = mask
    wrong_word = (rand > (p*.8)) & (rand <= (p*.9)) # 10% = wrong word
    x[wrong_word] = torch.randint(*word_range, [wrong_word.sum().item()], device=x.device)
    return x, y

# Utility for predictions
# def mask_note_or_dur(b):
#     x, y = b
#     x,x_pos = x[...,0], x[...,1]
#     y,y_pos = y[...,0], y[...,1]
#     x = x.clone()
#     rand = torch.rand(x.shape, device=x.device) < 0.9
#     mask_range = vocab.dur_range if random.randint(0, 1) == 0 else vocab.note_range
#     x[(x >= mask_range[0]) & (x < mask_range[1]) & rand] = vocab.mask_idx
#     return (x, None, y_pos, None), (y, MLMType.Mask)


# def mask_lm_tfm(b, mask_idx=vocab.mask_idx, pad_idx=vocab.pad_idx, p_mask=0.2):
def mask_lm_tfm(b, vocab, p_mask=0.2):
    x,y = b
    x_lm,x_pos = x[...,0], x[...,1]
    y_lm,y_pos = y[...,0], y[...,1]
    
    x_msk, y_msk = mask_tfm((y_lm, y_lm), vocab=vocab, p=p_mask) # masking instead of x. Just in case we ever do sequential s2s training
    msk_pos = y_pos
    
    x_dict = { 
        'msk': { 'x': x_msk, 'pos': msk_pos },
        'lm': { 'x': x_lm, 'pos': msk_pos }
    }
    y_dict = { 'msk': y_msk, 'lm': y_lm }
    return x_dict, y_dict

def melody_chord_tfm(b):
    m,m_pos,c,c_pos = b
    
    # offset x and y for next word prediction
    y_m = m[:,1:]
    x_m, m_pos = m[:,:-1], m_pos[:,:-1]
    
    y_c = c[:,1:]
    x_c, c_pos = c[:,:-1], c_pos[:,:-1]
    
    x_dict = { 
        'c2m': {
            'enc': x_c,
            'enc_pos': c_pos,
            'dec': x_m,
            'dec_pos': m_pos
        },
        'm2c': {
            'enc': x_m,
            'enc_pos': m_pos,
            'dec': x_c,
            'dec_pos': c_pos
        }
    }
    y_dict = {
        'c2m': y_m, 'm2c': y_c
    }
    return x_dict, y_dict
