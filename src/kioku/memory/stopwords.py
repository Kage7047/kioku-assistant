"""Function words dropped from BM25 queries and documents in hybrid search.

Measured in eval/: without them, BM25 returns weak matches on words like "what" or "the", and
fusion lets that noise outrank the right note found by the vector ranker (hybrid recall@5 0.82 →
0.97 on the sample set). They are kept in BM25-only mode, where they help slightly.
Covers the languages of the sample vault; extend for yours.
"""
_WORDS = """
a about after again all am an and any are as at avec avons be been before being below between both
but by can co con could cuándo czy d das de dem den der des did die do does doing don down du during
each ein eine el en es est et few for from further had has have having he her here hers him his how
i ich if ile in into is ist it its jest just la las le les ll los m me mich mir mit more most muss
my myself na nicht nie no nor not nous now of off on once only or other our ours out over own para
po por pour que quelles quels qui qué re s same she should się so some such sur t than that the
their them then there these they this those through to too un una und under une until up ve very w
wann was we wer were what when where which while who whom why wie will with would y you your yours z
zu
"""
STOPWORDS = frozenset(_WORDS.split())
